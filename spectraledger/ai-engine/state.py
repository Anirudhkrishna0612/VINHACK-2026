"""Live in-memory state: the simulated clock, recent telemetry per slice, and active leases.

Thread-safe (one RLock) because FastAPI runs sync endpoints in a thread pool while the
autonomous loop runs in its own thread.
"""
import threading
import time
from collections import deque
from datetime import timezone

import config
import telemetry


class LiveState:
    def __init__(self):
        self.lock = threading.RLock()
        self.history = {s["id"]: deque(maxlen=config.WINDOW * 6) for s in telemetry.SLICES}
        self.step = 0
        self.leases = []           # active capacity leases created by cleared trades
        self.ready = False

    def seed(self):
        """Pre-fill history so forecasts work on the very first tick (cold start)."""
        with self.lock:
            steps_per_day = 24 * 60 // config.STEP_MINUTES
            now_step = int(time.time() // 86400) * steps_per_day + int(config.SIM_START_HOUR * 60 // config.STEP_MINUTES)
            self.step = now_step
            for sl in telemetry.SLICES:
                dq = self.history[sl["id"]]
                dq.clear()
                for k in range(now_step - dq.maxlen + 1, now_step + 1):
                    dq.append(telemetry.sample(sl, k))
            self.ready = True

    def advance(self):
        """Move the simulated clock one step; return the fresh sample for every slice."""
        with self.lock:
            self.step += 1
            out = []
            for sl in telemetry.SLICES:
                smp = telemetry.sample(sl, self.step)
                self.history[sl["id"]].append(smp)
                out.append(self._decorate(sl, smp))
            return out

    def _decorate(self, sl, smp):
        d = dict(smp)
        d.update(workload_type=sl["type"], capacity_mbps=sl["capacity"], enterprise=sl["enterprise"],
                 sim_time=telemetry.step_to_datetime(smp["step"]).astimezone(timezone.utc).isoformat())
        return d

    def latest(self, slice_id):
        with self.lock:
            return self._decorate(telemetry.SLICE_BY_ID[slice_id], self.history[slice_id][-1])

    def window(self, slice_id, n=config.WINDOW):
        with self.lock:
            return list(self.history[slice_id])[-n:]

    # ---- leases ----
    def add_lease(self, trade_id, seller, buyer, qty):
        with self.lock:
            self.leases.append(dict(trade_id=trade_id, seller=seller, buyer=buyer, qty=qty,
                                    expires=time.monotonic() + config.LEASE_TTL_S))

    def expire_leases(self):
        with self.lock:
            now = time.monotonic()
            self.leases = [l for l in self.leases if l["expires"] > now]

    def leased_out(self, slice_id):
        with self.lock:
            now = time.monotonic()
            return sum(l["qty"] for l in self.leases if l["seller"] == slice_id and l["expires"] > now)

    def leased_in(self, slice_id):
        with self.lock:
            now = time.monotonic()
            return sum(l["qty"] for l in self.leases if l["buyer"] == slice_id and l["expires"] > now)


live = LiveState()
