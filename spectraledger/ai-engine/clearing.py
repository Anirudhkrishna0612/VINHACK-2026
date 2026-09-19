"""Turns a matched fill into a cleared trade: publish -> revenue -> lease -> webhook.

The trade is final the moment it is cleared here; the Java ledger receives it via webhook
and settles it. Revenue is recorded as an observer AFTER the price/quantity are fixed.
"""
import uuid
from datetime import datetime, timezone

import config
from events import bus
from revenue import revenue
from state import live
import webhook


def clear_trade(fill: dict) -> dict:
    price = round(fill["price"], 4)
    qty = round(fill["quantity_mbps"], 2)
    gross = round(price * qty, 4)
    fee = round(gross * config.PLATFORM_FEE_RATE, 4)
    trade = {
        "event_type": "trade.executed",
        "trade_id": f"T-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "buyer_slice_id": fill["buyer_slice_id"],
        "seller_slice_id": fill["seller_slice_id"],
        "buyer_enterprise": fill.get("buyer_enterprise", ""),
        "seller_enterprise": fill.get("seller_enterprise", ""),
        "workload_type": fill.get("workload_type", ""),
        "price": price,
        "quantity_mbps": qty,
        "gross_amount": gross,
        "platform_fee": fee,
        "net_to_seller": round(gross - fee, 4),
        "fee_rate": config.PLATFORM_FEE_RATE,
    }
    live.add_lease(trade["trade_id"], trade["seller_slice_id"], trade["buyer_slice_id"], qty)
    revenue.record(trade)
    bus.publish("trade.executed", trade)
    webhook.fire(trade)
    return trade
