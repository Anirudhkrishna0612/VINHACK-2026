"""Synthetic telemetry generator - the single source of truth for slice behaviour.

`sample(slice_def, step)` is a PURE function of (slice, integer step). Training-data
generation and the live feed both call exactly this function, so they can never disagree.
Noise and spikes come from a hash-based RNG keyed on (slice, step) instead of a stateful
RNG: the same step always yields the same value, and no shared mutable state exists.
"""
import math
from datetime import datetime, timedelta, timezone

from config import STEP_MINUTES

SLICES = [
    dict(id="slice-embb-01", enterprise="Meridian Stadium Media", type="eMBB", idx=0, capacity=1000.0,
         base=0.28, amp=1.5, phase=0.0, spike_p=0.08, spike_mag=0.35, lat=18.0),
    dict(id="slice-embb-02", enterprise="Harborline Retail Group", type="eMBB", idx=1, capacity=800.0,
         base=0.30, amp=1.5, phase=-3.0, spike_p=0.07, spike_mag=0.32, lat=20.0),
    dict(id="slice-urllc-01", enterprise="Apex Robotics Works", type="URLLC", idx=2, capacity=400.0,
         base=0.30, amp=1.4, phase=0.0, spike_p=0.10, spike_mag=0.42, lat=4.0),
    dict(id="slice-urllc-02", enterprise="Northgate Logistics", type="URLLC", idx=3, capacity=300.0,
         base=0.26, amp=1.4, phase=6.0, spike_p=0.09, spike_mag=0.40, lat=5.0),
    dict(id="slice-mmtc-01", enterprise="Verdant AgriSense", type="mMTC", idx=4, capacity=200.0,
         base=0.20, amp=0.8, phase=0.0, spike_p=0.05, spike_mag=0.25, lat=60.0),
    dict(id="slice-ai-01", enterprise="Helix AI Labs", type="AI_TRAINING", idx=5, capacity=2000.0,
         base=0.42, amp=1.4, phase=0.0, spike_p=0.12, spike_mag=0.32, lat=12.0),
]
SLICE_BY_ID = {s["id"]: s for s in SLICES}
WORKLOAD_TYPES = ["eMBB", "URLLC", "mMTC", "AI_TRAINING"]
TYPE_CODE = {t: i for i, t in enumerate(WORKLOAD_TYPES)}

_MASK = (1 << 64) - 1


def _hash_unit(a: int, b: int, salt: int) -> float:
    """splitmix64-style hash -> uniform float in [0,1). Deterministic, no state."""
    z = (a * 0x9E3779B97F4A7C15 + b * 0xBF58476D1CE4E5B9 + salt * 0x94D049BB133111EB + 0x1234567) & _MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
    z ^= z >> 31
    return (z >> 11) / float(1 << 53)


def _gauss(a: int, b: int, salt: int) -> float:
    u1 = max(_hash_unit(a, b, salt), 1e-12)
    u2 = _hash_unit(a, b, salt + 1)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _bump(hour: float, center: float, width: float) -> float:
    d = abs(hour - center)
    d = min(d, 24.0 - d)                      # circular distance on a 24h clock
    return math.exp(-0.5 * (d / width) ** 2)


def step_to_datetime(step: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=step * STEP_MINUTES)


def step_calendar(step: int):
    """(hour_of_day float, day_of_week 0=Mon) for an integer step."""
    dt = step_to_datetime(step)
    return dt.hour + dt.minute / 60.0, dt.weekday()


def _profile(stype: str, hour: float, dow: int) -> float:
    weekend = dow >= 5
    if stype == "eMBB":       # evening streaming peak + lunchtime bump
        return 0.34 * _bump(hour, 20.5, 2.6) + 0.16 * _bump(hour, 13.0, 2.0) + (0.06 if weekend else 0.0)
    if stype == "URLLC":      # factory-floor business-hours plateau
        p = 0.40 * _bump(hour, 13.0, 3.6)
        return p * (0.45 if weekend else 1.0)
    if stype == "mMTC":       # near-flat sensors, small overnight batch upload
        return 0.10 * _bump(hour, 3.0, 2.0) + 0.05 * _bump(hour, 15.0, 4.0)
    if stype == "AI_TRAINING":  # heavy overnight epochs + afternoon fine-tune jobs
        return 0.30 * _bump(hour, 1.5, 3.0) + 0.24 * _bump(hour, 15.0, 2.2)
    return 0.0


def _spike(sl: dict, step: int) -> float:
    """Occasional demand spikes: a triangular surge that can start in any hour-block."""
    total = 0.0
    block_len = 12                             # 12 steps = 1 simulated hour
    for b in (step // block_len, step // block_len - 1):
        if _hash_unit(sl["idx"] + 1, b, 11) < sl["spike_p"]:
            start = b * block_len + int(_hash_unit(sl["idx"] + 1, b, 13) * block_len)
            width = 4 + int(_hash_unit(sl["idx"] + 1, b, 17) * 5)
            mag = sl["spike_mag"] * (0.6 + 0.8 * _hash_unit(sl["idx"] + 1, b, 19))
            d = step - start
            if 0 <= d < width:
                total += mag * (1.0 - d / width)
    return total


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def sample(sl: dict, step: int) -> dict:
    hour, dow = step_calendar(step)
    shifted = (hour - sl["phase"]) % 24.0
    util = sl["base"] + sl["amp"] * _profile(sl["type"], shifted, dow)
    util += 0.025 * _gauss(sl["idx"] + 1, step, 3)
    util += 0.03 * math.sin(step / 7.0 + sl["idx"])
    util += _spike(sl, step)
    util = clamp01(max(0.02, util))            # clamp BEFORE it hits any schema requiring [0,1]
    tp = clamp01(util * (1.0 + 0.02 * _gauss(sl["idx"] + 1, step, 5))) * sl["capacity"]
    lat = sl["lat"] * (1.0 + 2.2 * util ** 4) * (1.0 + 0.04 * _gauss(sl["idx"] + 1, step, 7))
    return {
        "step": step,
        "slice_id": sl["id"],
        "utilization": round(util, 4),
        "throughput_mbps": round(tp, 2),
        "latency_ms": round(max(0.1, lat), 2),
    }
