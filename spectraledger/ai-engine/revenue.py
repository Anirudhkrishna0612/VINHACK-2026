"""Revenue module: a downstream OBSERVER of cleared trades.

It skims PLATFORM_FEE_RATE (default 2%) of each trade's notional. It never touches matching
or pricing - trades are recorded here only after they have already cleared.
"""
import threading

import config


class RevenueTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._trades = []
        self._fees = 0.0
        self._volume = 0.0

    def record(self, trade: dict):
        with self._lock:
            self._trades.append(dict(trade))
            self._fees += trade["platform_fee"]
            self._volume += trade["gross_amount"]

    def summary(self):
        with self._lock:
            n = len(self._trades)
            return {
                "fee_rate": config.PLATFORM_FEE_RATE,
                "trade_count": n,
                "total_volume": round(self._volume, 4),
                "total_platform_fees": round(self._fees, 4),
                "average_price": round(sum(t["price"] for t in self._trades) / n, 4) if n else 0.0,
            }

    def trades(self, limit=100):
        with self._lock:
            return list(reversed(self._trades[-limit:]))


revenue = RevenueTracker()
