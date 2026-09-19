"""Central, env-overridable settings for the AI engine.

Why one file: every threshold the demo may want to tweak live (SLA confidence gate,
safety ceiling, fee rate, loop speed) is here, so a judge can ask "what if the ceiling
were 80%?" and you change one env var, not five source files.
"""
import os


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# ---- outbound webhook to the Java ledger ----
BACKEND_TRADE_WEBHOOK = os.getenv("BACKEND_TRADE_WEBHOOK", "http://localhost:8080/api/trades/execute")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "spectraledger-demo-secret")
WEBHOOK_RETRIES = _i("WEBHOOK_RETRIES", 2)

# ---- revenue / fees (mirrored in backend application.yml) ----
PLATFORM_FEE_RATE = _f("PLATFORM_FEE_RATE", 0.02)

# ---- simulated clock ----
STEP_MINUTES = 5                                   # one telemetry sample = 5 simulated minutes
TELEMETRY_INTERVAL_S = _f("TELEMETRY_INTERVAL_S", 2.0)  # real seconds per sample (=> 1 sim day ~ 9.6 min)
AGENT_INTERVAL_S = _f("AGENT_INTERVAL_S", 8.0)     # the autonomous trading loop period
SIM_START_HOUR = _f("SIM_START_HOUR", 11.0)         # simulated time-of-day (UTC) the live feed starts at: busy periods arrive within minutes

# ---- forecasting ----
TRAIN_DAYS = _i("TRAIN_DAYS", 14)
DEFAULT_HORIZON_STEPS = _i("DEFAULT_HORIZON_STEPS", 6)  # 6 steps = 30 simulated minutes ahead
TRAIN_HORIZONS = (1, 3, 6, 12)
WINDOW = 12                                         # feature look-back (steps)
MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "forecast_models.joblib")

# ---- agent guardrails ----
SLA_CONFIDENCE_THRESHOLD = _f("SLA_CONFIDENCE_THRESHOLD", 0.50)  # below this a seller refuses to list
SAFETY_CEILING = _f("SAFETY_CEILING", 0.90)        # seller may never be pushed past this utilization
BUYER_TRIGGER_UTIL = _f("BUYER_TRIGGER_UTIL", 0.74)  # forecast p90 above this => buyer wants burst capacity
BUYER_TARGET_UTIL = _f("BUYER_TARGET_UTIL", 0.66)   # buyer sizes its order to get back down to this
MIN_LOT_MBPS = _f("MIN_LOT_MBPS", 10.0)
LEASE_TTL_S = _f("LEASE_TTL_S", 120.0)              # how long a cleared lease counts against headroom

# ---- pricing (USD per Mbps per 15-minute lease block) ----
BASE_RATES = {"eMBB": 0.10, "URLLC": 0.22, "mMTC": 0.05, "AI_TRAINING": 0.14}
QOS_WEIGHTS = {"eMBB": 1.0, "URLLC": 1.5, "mMTC": 0.8, "AI_TRAINING": 1.15}
