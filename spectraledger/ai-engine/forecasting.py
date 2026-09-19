"""LightGBM forecasting: point + 10th/90th percentile quantile models.

Three separate LightGBM models are trained on identical features:
  * point  (objective=regression)         -> best guess
  * q10    (objective=quantile, alpha=.1) -> lower bound
  * q90    (objective=quantile, alpha=.9) -> upper bound
The 10-90 band is a learned prediction interval (it widens when the series is volatile),
not a fixed +/- guess. confidence_score is derived from the band width.
"""
import math
import os
import time

import joblib
import lightgbm as lgb
import numpy as np

import config
import telemetry
from state import live

FEATURE_NAMES = [
    "tod_sin", "tod_cos", "dow_sin", "dow_cos",
    "util_now", "throughput_now", "latency_now",
    "roll_mean", "roll_std", "slope",
    "slice_type", "slice_idx", "horizon",
]

_models = None


def features_from_window(util, tp, lat, step, sl, horizon):
    """THE feature function - used identically for training rows and live inference."""
    target_step = step + horizon
    hour, dow = telemetry.step_calendar(target_step)
    tod = 2 * math.pi * hour / 24.0
    dw = 2 * math.pi * dow / 7.0
    u = np.asarray(util, dtype=float)
    k = min(6, len(u))
    y = u[-k:]
    x = np.arange(k, dtype=float)
    slope = float(((x - x.mean()) * (y - y.mean())).sum() / max(((x - x.mean()) ** 2).sum(), 1e-9)) if k > 1 else 0.0
    return [
        math.sin(tod), math.cos(tod), math.sin(dw), math.cos(dw),
        float(u[-1]), float(tp[-1]), float(lat[-1]),
        float(u.mean()), float(u.std()), slope,
        telemetry.TYPE_CODE[sl["type"]], sl["idx"], float(horizon),
    ]


def build_training_frame(days=config.TRAIN_DAYS, stride=2):
    steps_per_day = 24 * 60 // config.STEP_MINUTES
    end = int(time.time() // (60 * config.STEP_MINUTES))
    start = end - days * steps_per_day
    rows, targets = [], []
    for sl in telemetry.SLICES:
        series = [telemetry.sample(sl, k) for k in range(start, end + max(config.TRAIN_HORIZONS) + 1)]
        u = [s["utilization"] for s in series]
        tp = [s["throughput_mbps"] for s in series]
        la = [s["latency_ms"] for s in series]
        for t in range(config.WINDOW, len(series) - max(config.TRAIN_HORIZONS) - 1, stride):
            for h in config.TRAIN_HORIZONS:
                rows.append(features_from_window(u[t - config.WINDOW + 1:t + 1], tp[t - config.WINDOW + 1:t + 1],
                                                 la[t - config.WINDOW + 1:t + 1], start + t, sl, h))
                targets.append(u[t + h])
    return np.array(rows, dtype=float), np.array(targets, dtype=float)


def train(verbose=True):
    t0 = time.time()
    X, y = build_training_frame()
    if verbose:
        print(f"[forecast] training on {len(X)} rows ...", flush=True)
    common = dict(n_estimators=250, learning_rate=0.05, num_leaves=31, min_child_samples=40,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.9, verbose=-1, n_jobs=2)
    n = len(X)
    cut = int(n * 0.85)                        # simple hold-out just to report an honest error
    point = lgb.LGBMRegressor(objective="regression", **common).fit(X[:cut], y[:cut])
    mae = float(np.mean(np.abs(point.predict(X[cut:]) - y[cut:])))
    qcommon = dict(common, num_leaves=15, min_child_samples=120, n_estimators=150)  # regularized: wider, honest bands
    q10 = lgb.LGBMRegressor(objective="quantile", alpha=0.10, **qcommon).fit(X, y)
    q90 = lgb.LGBMRegressor(objective="quantile", alpha=0.90, **qcommon).fit(X, y)
    point = lgb.LGBMRegressor(objective="regression", **common).fit(X, y)
    models = {"point": point, "q10": q10, "q90": q90, "holdout_mae": mae, "trained_rows": n}
    os.makedirs(os.path.dirname(config.MODEL_PATH), exist_ok=True)
    joblib.dump(models, config.MODEL_PATH)
    if verbose:
        print(f"[forecast] trained in {time.time() - t0:.1f}s, hold-out MAE={mae:.4f} (utilization units)", flush=True)
    return models


def load_or_train():
    global _models
    if os.path.exists(config.MODEL_PATH):
        try:
            _models = joblib.load(config.MODEL_PATH)
            print(f"[forecast] loaded saved models from {config.MODEL_PATH}", flush=True)
            return _models
        except Exception as exc:  # corrupted file -> retrain
            print(f"[forecast] could not load saved model ({exc}); retraining", flush=True)
    _models = train()
    return _models


def forecast(slice_id, horizon_steps=config.DEFAULT_HORIZON_STEPS):
    if _models is None:
        load_or_train()
    sl = telemetry.SLICE_BY_ID[slice_id]
    win = live.window(slice_id)
    x = np.array([features_from_window([w["utilization"] for w in win], [w["throughput_mbps"] for w in win],
                                       [w["latency_ms"] for w in win], win[-1]["step"], sl, horizon_steps)])
    p = float(_models["point"].predict(x)[0])
    lo = float(_models["q10"].predict(x)[0])
    hi = float(_models["q90"].predict(x)[0])
    lo, hi = sorted((lo, hi))
    lo, hi = telemetry.clamp01(lo), telemetry.clamp01(hi)
    p = min(max(p, lo), hi)                    # keep the point inside its own interval
    width = hi - lo
    confidence = max(0.0, min(1.0, 1.0 - width / 0.30))
    return {
        "slice_id": slice_id,
        "workload_type": sl["type"],
        "horizon_steps": horizon_steps,
        "horizon_minutes": horizon_steps * config.STEP_MINUTES,
        "current_utilization": win[-1]["utilization"],
        "forecast_utilization": round(p, 4),
        "p10": round(lo, 4),
        "p90": round(hi, 4),
        "interval_width": round(width, 4),
        "confidence_score": round(confidence, 4),
        "capacity_mbps": sl["capacity"],
        "forecast_demand_mbps": round(p * sl["capacity"], 1),
        "p90_demand_mbps": round(hi * sl["capacity"], 1),
    }
