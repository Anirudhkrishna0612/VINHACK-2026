"""POST /agent/negotiate engine: real seller/buyer agents set the opening quotes, then the
gap is narrowed by bisection for up to 4 rounds. Each round both sides concede 25% of the gap
(so the gap halves), but never past their own reservation price:
  seller reservation = the price its own agent computed (won't sell below it)
  buyer  reservation = the price its own agent computed (won't pay above it)
"""
import agents
import clearing
from events import bus

MAX_ROUNDS = 4
OPEN_PREMIUM = 1.30     # seller opens 30% above its reservation
OPEN_DISCOUNT = 0.70    # buyer opens 30% below its reservation
DEFAULT_LOT = 50.0


def negotiate(seller_slice_id, buyer_slice_id, quantity_mbps=None, execute=False):
    s = agents.run_agent(seller_slice_id, "seller")
    b = agents.run_agent(buyer_slice_id, "buyer")
    res_seller, res_buyer = s["price"]["price"], b["price"]["price"]
    ask = round(res_seller * OPEN_PREMIUM, 4)
    bid = round(min(res_buyer, ask) * OPEN_DISCOUNT, 4)     # buyer lowballs the posted ask, never above its own ceiling

    notes = []
    if quantity_mbps:
        qty = float(quantity_mbps)
    else:
        cands = [q for q in (s["decision"]["quantity_mbps"], b["decision"]["quantity_mbps"]) if q > 0]
        qty = min(cands) if len(cands) == 2 else DEFAULT_LOT
        if len(cands) < 2:
            notes.append(f"Agents did not both have an active order right now (seller: {s['decision']['action']}, "
                         f"buyer: {b['decision']['action']}); negotiating a {DEFAULT_LOT:.0f} Mbps demonstration lot.")

    rounds = [{"round": 0, "seller_ask": ask, "buyer_bid": bid, "gap": round(ask - bid, 4),
               "note": f"Opening quotes: seller lists at {OPEN_PREMIUM:.0%} of its reservation, buyer opens {1 - OPEN_DISCOUNT:.0%} below the lower of the ask and its own ceiling."}]
    outcome, agreed = "no_deal", None
    for r in range(1, MAX_ROUNDS + 1):
        gap = ask - bid
        if gap <= 0:
            agreed = round((ask + bid) / 2, 4); outcome = "deal"; break
        step = 0.25 * gap
        new_ask, new_bid = max(res_seller, ask - step), min(res_buyer, bid + step)
        stuck = []
        if new_ask == res_seller and ask - step < res_seller:
            stuck.append("seller hit its floor")
        if new_bid == res_buyer and bid + step > res_buyer:
            stuck.append("buyer hit its ceiling")
        ask, bid = round(new_ask, 4), round(new_bid, 4)
        mid = (ask + bid) / 2
        rounds.append({"round": r, "seller_ask": ask, "buyer_bid": bid, "gap": round(ask - bid, 4),
                       "note": "Both sides concede toward the midpoint" + (f" ({', '.join(stuck)})" if stuck else "") + "."})
        if ask - bid <= 0.05 * mid:
            agreed = round(min(max(mid, res_seller), res_buyer), 4) if res_seller <= res_buyer else None
            if agreed is not None:
                outcome = "deal"; break
    if outcome == "no_deal" and res_seller <= res_buyer:
        agreed = round(min(max((ask + bid) / 2, res_seller), res_buyer), 4)
        outcome = "deal"
        notes.append("Round limit reached; sides closed at the midpoint inside their reservation prices.")
    if outcome == "no_deal":
        if res_seller > res_buyer:
            notes.append(f"No overlap: seller's floor ${res_seller:.4f} is above buyer's ceiling ${res_buyer:.4f}.")
        else:
            notes.append("Gap did not close within 4 rounds.")

    result = {"seller_slice_id": seller_slice_id, "buyer_slice_id": buyer_slice_id, "quantity_mbps": qty,
              "seller_reservation": res_seller, "buyer_reservation": res_buyer, "outcome": outcome,
              "agreed_price": agreed, "rounds": rounds, "notes": notes,
              "seller_reasoning": s["trace"], "buyer_reasoning": b["trace"], "trade": None}
    if outcome == "deal":
        if execute:
            result["trade"] = clearing.clear_trade({
                "price": agreed, "quantity_mbps": qty, "buyer_slice_id": buyer_slice_id,
                "seller_slice_id": seller_slice_id, "buyer_enterprise": b["decision"]["enterprise"],
                "seller_enterprise": s["decision"]["enterprise"], "workload_type": s["decision"]["workload_type"]})
        bus.publish("agent.decision", {
            "slice_id": buyer_slice_id, "enterprise": b["decision"]["enterprise"], "role": "buyer",
            "workload_type": b["decision"]["workload_type"], "action": "NEGOTIATED", "price": agreed,
            "quantity_mbps": qty, "confidence": b["forecast"]["confidence_score"],
            "forecast_utilization": b["forecast"]["forecast_utilization"], "matched": execute,
            "trade_ids": [result["trade"]["trade_id"]] if result["trade"] else [],
            "reason": f"Negotiated with {seller_slice_id} in {len(rounds) - 1} round(s), settled at ${agreed:.4f}/Mbps."})
    return result
