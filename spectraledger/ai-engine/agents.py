"""Autonomous seller/buyer agents as a LangGraph state machine.

    read_state -> evaluate -> sla_gate --(refused)--------------------> decide -> confirm_trade
                                   \\--(ok)--> safety_cap ------------> decide -> confirm_trade

* evaluate    : calls the REAL forecast() and compute_price() functions (no mocks).
* sla_gate    : a seller refuses to list when forecast confidence is below the threshold.
* safety_cap  : a seller can never list enough to push its OWN utilization past the ceiling.
* confirm_trade: checks (dry run) or executes (commit) against the live order book.
Why LangGraph: each guardrail is an explicit node, so the reasoning trace we stream to the UI
is literally the path the graph took - the "AI is thinking" demo is not decoration.
"""
import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import clearing
import config
import forecasting
import telemetry
from events import bus
from orderbook import book
from pricing import compute_price
from state import live


class AgentState(TypedDict, total=False):
    slice_id: str
    role: str                       # "seller" | "buyer"
    commit: bool
    horizon_steps: int
    explicit_book: Optional[dict]
    snapshot: dict
    forecast: dict
    price: dict
    raw_qty: float
    qty: float
    gate: dict
    decision: dict
    match: dict
    trace: Annotated[list, operator.add]


def _pct(x):
    return f"{x * 100:.0f}%"


# ---------------- nodes ----------------
def read_state(s: AgentState):
    sl = telemetry.SLICE_BY_ID[s["slice_id"]]
    snap = live.latest(s["slice_id"])
    snap["leased_out_mbps"] = round(live.leased_out(s["slice_id"]), 2)
    snap["leased_in_mbps"] = round(live.leased_in(s["slice_id"]), 2)
    return {"snapshot": snap, "trace": [
        f"read_state: {sl['enterprise']} ({sl['type']}) at {_pct(snap['utilization'])} utilization, "
        f"{snap['throughput_mbps']:.0f}/{sl['capacity']:.0f} Mbps, latency {snap['latency_ms']} ms."]}


def evaluate(s: AgentState):
    sl = telemetry.SLICE_BY_ID[s["slice_id"]]
    fc = forecasting.forecast(s["slice_id"], s.get("horizon_steps", config.DEFAULT_HORIZON_STEPS))
    if s["role"] == "seller":
        urgency = max(0.0, 0.6 - fc["forecast_utilization"])          # idle capacity is eager to be monetized
        price = compute_price(sl["type"], fc["forecast_utilization"], urgency, "sell")
        raw = sl["capacity"] * (1.0 - fc["p90"])                       # forecast idle capacity even at the p90 peak
    else:
        urgency = max(0.0, min(1.0, (fc["p90"] - config.BUYER_TRIGGER_UTIL) / (1.0 - config.BUYER_TRIGGER_UTIL)))
        price = compute_price(sl["type"], fc["p90"], urgency, "buy")   # buyer prices in the expected peak
        raw = sl["capacity"] * (fc["p90"] - config.BUYER_TARGET_UTIL) if fc["p90"] > config.BUYER_TRIGGER_UTIL else 0.0
    return {"forecast": fc, "price": price, "raw_qty": max(0.0, raw), "trace": [
        f"evaluate: forecast {_pct(fc['forecast_utilization'])} in {fc['horizon_minutes']} min "
        f"(p10 {_pct(fc['p10'])} - p90 {_pct(fc['p90'])}), confidence {_pct(fc['confidence_score'])}. "
        f"Price: {price['explanation']}"]}


def sla_gate(s: AgentState):
    fc = s["forecast"]
    if s["role"] == "seller" and fc["confidence_score"] < config.SLA_CONFIDENCE_THRESHOLD:
        reason = (f"Forecast confidence {_pct(fc['confidence_score'])} is below the {_pct(config.SLA_CONFIDENCE_THRESHOLD)} SLA-risk "
                  f"threshold (10-90% band is {_pct(fc['p10'])}-{_pct(fc['p90'])}, too wide). Refusing to list capacity "
                  f"that I might suddenly need myself.")
        return {"gate": {"passed": False, "reason": reason}, "trace": [f"sla_gate: REFUSED - {reason}"]}
    return {"gate": {"passed": True, "reason": "ok"}, "trace": [
        f"sla_gate: passed (confidence {_pct(fc['confidence_score'])} >= {_pct(config.SLA_CONFIDENCE_THRESHOLD)})."
        if s["role"] == "seller" else "sla_gate: not applicable to buyers."]}


def route_after_gate(s: AgentState):
    return "safety_cap" if s["gate"]["passed"] else "decide"


def safety_cap(s: AgentState):
    sl = telemetry.SLICE_BY_ID[s["slice_id"]]
    fc = s["forecast"]
    sid = s["slice_id"]
    safe = 0.0
    if s["role"] == "seller":
        committed = live.leased_out(sid) + book.open_quantity(sid, "ask", source="manual")
        safe = sl["capacity"] * (config.SAFETY_CEILING - fc["p90"]) - committed
        qty = max(0.0, min(s["raw_qty"], safe))
        note = (f"safety_cap: idle capacity {s['raw_qty']:.0f} Mbps, but keeping my own utilization <= {_pct(config.SAFETY_CEILING)} "
                f"at the p90 forecast leaves {max(safe, 0):.0f} Mbps (after {committed:.0f} Mbps already committed) -> may list {qty:.0f} Mbps.")
    else:
        committed = live.leased_in(sid) + book.open_quantity(sid, "bid", source="manual")
        qty = max(0.0, s["raw_qty"] - committed)
        note = (f"safety_cap: burst need {s['raw_qty']:.0f} Mbps to get back to {_pct(config.BUYER_TARGET_UTIL)}, "
                f"minus {committed:.0f} Mbps already leased/bid -> need {qty:.0f} Mbps.")
    qty = int(qty * 10) / 10.0                                          # floor to 0.1 Mbps: never round UP past the cap
    return {"qty": qty, "committed": committed, "safe_mbps": max(safe, 0.0) if s["role"] == "seller" else 0.0, "trace": [note]}


def decide(s: AgentState):
    sl = telemetry.SLICE_BY_ID[s["slice_id"]]
    fc, price = s["forecast"], s["price"]
    base = dict(slice_id=s["slice_id"], enterprise=sl["enterprise"], role=s["role"], workload_type=sl["type"])
    if s["role"] == "seller":
        if not s["gate"]["passed"]:
            d = dict(base, action="REFUSE_SLA", price=None, quantity_mbps=0.0, reason=s["gate"]["reason"])
        elif s["qty"] < config.MIN_LOT_MBPS:
            d = dict(base, action="NO_SURPLUS", price=None, quantity_mbps=0.0,
                     reason=f"Only {s['qty']:.0f} Mbps could be listed safely (minimum lot {config.MIN_LOT_MBPS:.0f}): {s.get('committed', 0):.0f} Mbps is already leased out or "
                            f"committed, and at the p90 forecast of {_pct(fc['p90'])} the {_pct(config.SAFETY_CEILING)} safety ceiling leaves only {s.get('safe_mbps', 0):.0f} Mbps. Holding.")
        else:
            d = dict(base, action="LIST_ASK", price=price["price"], quantity_mbps=s["qty"],
                     reason=f"Forecast {_pct(fc['forecast_utilization'])} (p90 {_pct(fc['p90'])}), confidence {_pct(fc['confidence_score'])}. "
                            f"Safe to lease out {s['qty']:.0f} Mbps without breaching my {_pct(config.SAFETY_CEILING)} ceiling. "
                            f"Asking ${price['price']:.4f}/Mbps. {price['explanation']}")
    else:
        if s["qty"] < config.MIN_LOT_MBPS:
            d = dict(base, action="NO_DEMAND", price=None, quantity_mbps=0.0,
                     reason=f"Forecast p90 {_pct(fc['p90'])} is under my {_pct(config.BUYER_TRIGGER_UTIL)} burst trigger (or already covered). No burst capacity needed.")
        else:
            d = dict(base, action="POST_BID", price=price["price"], quantity_mbps=s["qty"],
                     reason=f"Forecast peak {_pct(fc['p90'])} exceeds my {_pct(config.BUYER_TRIGGER_UTIL)} trigger - I need {s['qty']:.0f} Mbps of instant burst capacity. "
                            f"Bidding ${price['price']:.4f}/Mbps. {price['explanation']}")
    return {"decision": d, "trace": [f"decide: {d['action']} - {d['reason']}"]}


def confirm_trade(s: AgentState):
    d = s["decision"]
    if d["action"] not in ("LIST_ASK", "POST_BID"):
        if s.get("commit") and s.get("explicit_book") is None:
            book.cancel_agent_orders(d["slice_id"], side="ask" if s["role"] == "seller" else "bid")  # withdraw stale quote
        return {"match": {"matched": False, "note": "nothing to place"}, "trace": ["confirm_trade: no order placed."]}
    side = "ask" if d["action"] == "LIST_ASK" else "bid"
    explicit = s.get("explicit_book")
    if explicit is not None or not s.get("commit"):
        hit = book.peek_match(side, d["slice_id"], d["price"], explicit)
        src = "supplied order book" if explicit is not None else "live order book"
        m = {"matched": False, "dry_run": True, "would_match": hit is not None, "counterparty": hit}
        msg = (f"confirm_trade (dry run, {src}): would match {hit['quantity_mbps']:.0f} Mbps from {hit['slice_id']} at ${hit['price']:.4f}."
               if hit else f"confirm_trade (dry run, {src}): no crossing order - would rest in the book.")
        return {"match": m, "trace": [msg]}
    book.cancel_agent_orders(d["slice_id"], side=side)                   # re-quote: replace my previous agent order
    order = book.add(d["slice_id"], side, d["price"], d["quantity_mbps"], source="agent",
                     enterprise=d["enterprise"], workload_type=d["workload_type"])
    fills = book.match_order(order["id"])
    trades = [clearing.clear_trade(f) for f in fills]
    m = {"matched": bool(trades), "dry_run": False, "order": order, "trades": trades}
    if trades:
        tot = sum(t["quantity_mbps"] for t in trades)
        msg = f"confirm_trade: MATCHED {tot:.0f} Mbps in {len(trades)} trade(s), first at ${trades[0]['price']:.4f} (trade {trades[0]['trade_id']})."
    else:
        msg = f"confirm_trade: no crossing order; resting {side} {order['id']} in the order book."
    return {"match": m, "trace": [msg]}


def _build():
    g = StateGraph(AgentState)
    for name, fn in [("read_state", read_state), ("evaluate", evaluate), ("sla_gate", sla_gate),
                     ("safety_cap", safety_cap), ("decide", decide), ("confirm_trade", confirm_trade)]:
        g.add_node(name, fn)
    g.add_edge(START, "read_state")
    g.add_edge("read_state", "evaluate")
    g.add_edge("evaluate", "sla_gate")
    g.add_conditional_edges("sla_gate", route_after_gate, {"safety_cap": "safety_cap", "decide": "decide"})
    g.add_edge("safety_cap", "decide")
    g.add_edge("decide", "confirm_trade")
    g.add_edge("confirm_trade", END)
    return g.compile()


GRAPH = _build()


def run_agent(slice_id: str, role: str, commit: bool = False, explicit_book: Optional[dict] = None,
              horizon_steps: int = config.DEFAULT_HORIZON_STEPS) -> dict[str, Any]:
    if slice_id not in telemetry.SLICE_BY_ID:
        raise KeyError(slice_id)
    if role not in ("seller", "buyer"):
        raise ValueError("role must be 'seller' or 'buyer'")
    out = GRAPH.invoke({"slice_id": slice_id, "role": role, "commit": commit, "explicit_book": explicit_book,
                        "horizon_steps": horizon_steps, "trace": []})
    result = {"slice_id": slice_id, "role": role, "committed": bool(commit and explicit_book is None),
              "decision": out["decision"], "forecast": out["forecast"], "price": out["price"],
              "match": out["match"], "trace": out["trace"]}
    d = out["decision"]
    if commit and explicit_book is None and not (role == "buyer" and d["action"] == "NO_DEMAND"):
        bus.publish("agent.decision", {
            **{k: d[k] for k in ("slice_id", "enterprise", "role", "workload_type", "action", "price", "quantity_mbps", "reason")},
            "confidence": out["forecast"]["confidence_score"],
            "forecast_utilization": out["forecast"]["forecast_utilization"],
            "matched": bool(out["match"].get("matched")),
            "trade_ids": [t["trade_id"] for t in out["match"].get("trades", [])],
        })
    return result
