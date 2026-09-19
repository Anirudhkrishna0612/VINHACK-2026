"""Persistent (in-memory, process-lifetime) limit order book with price-time priority.

Matching rule: a bid and an ask cross when bid.price >= ask.price and they belong to
different slices. The trade clears at the MIDPOINT of bid and ask (the call-auction convention):
the buyer pays less than it was willing to and the seller gets more than it asked, so the
surplus is split evenly and it does not matter whose quote happened to arrive first. Quantity
is min(bid qty, ask qty). Best-priced counterparties are matched first (ties: oldest first).
"""
import itertools
import threading
from datetime import datetime, timezone


class OrderBook:
    def __init__(self):
        self._lock = threading.RLock()
        self._orders = {}
        self._seq = itertools.count(1)

    # ---- mutation ----
    def add(self, slice_id, side, price, quantity_mbps, source="agent", enterprise="", workload_type=""):
        if side not in ("bid", "ask"):
            raise ValueError("side must be 'bid' or 'ask'")
        if price <= 0 or quantity_mbps <= 0:
            raise ValueError("price and quantity_mbps must be positive")
        with self._lock:
            seq = next(self._seq)
            order = {"id": f"O-{seq:06d}", "seq": seq, "slice_id": slice_id, "enterprise": enterprise,
                     "workload_type": workload_type, "side": side, "price": round(float(price), 4),
                     "quantity_mbps": round(float(quantity_mbps), 2), "source": source,
                     "created_at": datetime.now(timezone.utc).isoformat()}
            self._orders[order["id"]] = order
            return dict(order)

    def cancel(self, order_id):
        with self._lock:
            return self._orders.pop(order_id, None) is not None

    def cancel_agent_orders(self, slice_id=None, side=None):
        with self._lock:
            ids = [i for i, o in self._orders.items()
                   if o["source"] == "agent" and (slice_id is None or o["slice_id"] == slice_id)
                   and (side is None or o["side"] == side)]
            for i in ids:
                del self._orders[i]
            return len(ids)

    # ---- reads ----
    def snapshot(self):
        with self._lock:
            bids = sorted((dict(o) for o in self._orders.values() if o["side"] == "bid"),
                          key=lambda o: (-o["price"], o["seq"]))
            asks = sorted((dict(o) for o in self._orders.values() if o["side"] == "ask"),
                          key=lambda o: (o["price"], o["seq"]))
            return {"bids": bids, "asks": asks}

    def open_quantity(self, slice_id, side, source=None):
        with self._lock:
            return sum(o["quantity_mbps"] for o in self._orders.values()
                       if o["slice_id"] == slice_id and o["side"] == side and (source is None or o["source"] == source))

    # ---- matching ----
    @staticmethod
    def _best_counterparty(side, slice_id, price, candidates):
        if side == "bid":
            pool = [o for o in candidates if o["side"] == "ask" and o["slice_id"] != slice_id and o["price"] <= price]
            return min(pool, key=lambda o: (o["price"], o["seq"]), default=None)
        pool = [o for o in candidates if o["side"] == "bid" and o["slice_id"] != slice_id and o["price"] >= price]
        return max(pool, key=lambda o: (o["price"], -o["seq"]), default=None)

    def peek_match(self, side, slice_id, price, explicit_book=None):
        """Read-only: which resting order WOULD this quote hit? explicit_book overrides the live book."""
        if explicit_book is not None:
            cands = []
            for s, key in (("bid", "bids"), ("ask", "asks")):
                for i, o in enumerate(explicit_book.get(key, []) or []):
                    cands.append({"id": o.get("id", f"ext-{s}-{i}"), "seq": i, "side": s,
                                  "slice_id": o.get("slice_id", "external"), "price": float(o["price"]),
                                  "quantity_mbps": float(o.get("quantity_mbps", 0))})
            return self._best_counterparty(side, slice_id, price, cands)
        with self._lock:
            hit = self._best_counterparty(side, slice_id, price, list(self._orders.values()))
            return dict(hit) if hit else None

    def match_order(self, order_id):
        """Match one resting order against the opposite side; returns a list of fills."""
        fills = []
        with self._lock:
            while True:
                o = self._orders.get(order_id)
                if o is None:
                    break
                other = self._best_counterparty(o["side"], o["slice_id"], o["price"], list(self._orders.values()))
                if other is None:
                    break
                qty = round(min(o["quantity_mbps"], other["quantity_mbps"]), 2)
                bid, ask = (o, other) if o["side"] == "bid" else (other, o)
                fills.append({"price": round((bid["price"] + ask["price"]) / 2.0, 4), "quantity_mbps": qty,
                              "buyer_slice_id": bid["slice_id"], "seller_slice_id": ask["slice_id"],
                              "buyer_enterprise": bid["enterprise"], "seller_enterprise": ask["enterprise"],
                              "workload_type": ask["workload_type"],
                              "bid_order_id": bid["id"], "ask_order_id": ask["id"]})
                for x in (o, other):
                    x["quantity_mbps"] = round(x["quantity_mbps"] - qty, 2)
                    if x["quantity_mbps"] < 0.01:
                        self._orders.pop(x["id"], None)
        return fills

    def sweep(self):
        """Clear every crossed pair in the book (this is what fills human-submitted orders)."""
        fills = []
        with self._lock:
            for oid in [o["id"] for o in sorted(self._orders.values(), key=lambda o: o["seq"])]:
                fills.extend(self.match_order(oid))
        return fills


book = OrderBook()
