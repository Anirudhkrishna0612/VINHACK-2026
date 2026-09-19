"""SpectraLedger AI engine - FastAPI on port 8000. Start with:  python main.py"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import agents
import config
import forecasting
import loop
import negotiate as negotiate_mod
import telemetry
import webhook
from events import TOPICS, bus
from orderbook import book
from pricing import compute_price
from revenue import revenue
from state import live

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    running = asyncio.get_running_loop()
    bus.bind_loop(running)
    webhook.bind_loop(running)
    await asyncio.to_thread(forecasting.load_or_train)      # auto-train on first startup if no saved model
    live.seed()                                             # pre-fill history so tick #1 can forecast
    tasks = [asyncio.create_task(loop.telemetry_task()), asyncio.create_task(loop.agent_task())]
    log.info("autonomous loop started: telemetry every %.1fs, agents every %.1fs -> %s",
             config.TELEMETRY_INTERVAL_S, config.AGENT_INTERVAL_S, config.BACKEND_TRADE_WEBHOOK)
    yield
    for t in tasks:
        t.cancel()
    await webhook.close()


app = FastAPI(title="SpectraLedger AI Engine", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- schemas ----------
class ForecastRequest(BaseModel):
    slice_id: str
    horizon_steps: int = Field(config.DEFAULT_HORIZON_STEPS, ge=1, le=24)


class PriceRequest(BaseModel):
    workload_type: Optional[str] = None
    slice_id: Optional[str] = None
    utilization: float = Field(..., ge=0.0, le=1.0)
    urgency: float = Field(0.0, ge=0.0, le=1.0)
    side: str = Field("sell", pattern="^(buy|sell)$")


class EvaluateRequest(BaseModel):
    slice_id: str
    role: str = Field(..., pattern="^(seller|buyer)$")
    order_book: Optional[dict] = None       # {"bids":[{price,quantity_mbps,slice_id}], "asks":[...]} - dry run only
    commit: bool = False                    # False = advisory dry run; True = place order + clear matches
    horizon_steps: int = Field(config.DEFAULT_HORIZON_STEPS, ge=1, le=24)


class OrderRequest(BaseModel):
    slice_id: str
    side: str = Field(..., pattern="^(bid|ask)$")
    price: float = Field(..., gt=0)
    quantity_mbps: float = Field(..., gt=0)


class NegotiateRequest(BaseModel):
    seller_slice_id: str
    buyer_slice_id: str
    quantity_mbps: Optional[float] = Field(None, gt=0)
    execute: bool = False                   # True = clear the agreed deal as a real trade (fires webhook)


def _need_slice(sid):
    if sid not in telemetry.SLICE_BY_ID:
        raise HTTPException(404, f"unknown slice_id '{sid}'. Valid: {list(telemetry.SLICE_BY_ID)}")


# ---------- meta ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "spectraledger-ai-engine", "model_loaded": forecasting._models is not None,
            "live_ready": live.ready, "sim_step": live.step, "loop": loop.stats, "trades_cleared": revenue.summary()["trade_count"], "webhook": webhook.stats(),
            "open_orders": len(book.snapshot()["bids"]) + len(book.snapshot()["asks"])}


@app.get("/slices")
def slices():
    return [{**s, "latest": live.latest(s["id"]) if live.ready else None} for s in telemetry.SLICES]


@app.get("/config")
def get_config():
    return {k: getattr(config, k) for k in ("SLA_CONFIDENCE_THRESHOLD", "SAFETY_CEILING", "BUYER_TRIGGER_UTIL",
            "BUYER_TARGET_UTIL", "MIN_LOT_MBPS", "PLATFORM_FEE_RATE", "AGENT_INTERVAL_S", "TELEMETRY_INTERVAL_S",
            "BACKEND_TRADE_WEBHOOK", "BASE_RATES", "QOS_WEIGHTS")}


# ---------- core AI ----------
@app.post("/forecast")
def post_forecast(req: ForecastRequest):
    _need_slice(req.slice_id)
    return forecasting.forecast(req.slice_id, req.horizon_steps)


@app.post("/price")
def post_price(req: PriceRequest):
    wt = req.workload_type
    if req.slice_id:
        _need_slice(req.slice_id)
        wt = telemetry.SLICE_BY_ID[req.slice_id]["type"]
    if wt not in config.BASE_RATES:
        raise HTTPException(422, f"workload_type must be one of {list(config.BASE_RATES)}")
    return compute_price(wt, req.utilization, req.urgency, req.side)


@app.post("/agent/evaluate")
def post_evaluate(req: EvaluateRequest):
    _need_slice(req.slice_id)
    return agents.run_agent(req.slice_id, req.role, commit=req.commit, explicit_book=req.order_book,
                            horizon_steps=req.horizon_steps)


@app.post("/agent/negotiate")
def post_negotiate(req: NegotiateRequest):
    _need_slice(req.seller_slice_id)
    _need_slice(req.buyer_slice_id)
    if req.seller_slice_id == req.buyer_slice_id:
        raise HTTPException(422, "seller and buyer must be different slices")
    return negotiate_mod.negotiate(req.seller_slice_id, req.buyer_slice_id, req.quantity_mbps, req.execute)


# ---------- order book ----------
@app.get("/orderbook")
def get_orderbook():
    return book.snapshot()


@app.post("/orderbook/orders", status_code=201)
def post_order(req: OrderRequest):
    _need_slice(req.slice_id)
    sl = telemetry.SLICE_BY_ID[req.slice_id]
    return book.add(req.slice_id, req.side, req.price, req.quantity_mbps, source="manual",
                    enterprise=sl["enterprise"], workload_type=sl["type"])


@app.delete("/orderbook/orders/{order_id}")
def delete_order(order_id: str):
    if not book.cancel(order_id):
        raise HTTPException(404, "order not found")
    return {"cancelled": order_id}


# ---------- revenue ----------
@app.get("/revenue/summary")
def revenue_summary():
    return revenue.summary()


@app.get("/revenue/trades")
def revenue_trades(limit: int = Query(100, ge=1, le=1000)):
    return revenue.trades(limit)


# ---------- events ----------
@app.get("/events/{topic}")
def get_events(topic: str, limit: int = Query(50, ge=1, le=500), after: int = Query(0, ge=0)):
    if topic not in TOPICS:
        raise HTTPException(404, f"unknown topic. Valid: {list(TOPICS)}")
    return bus.recent(topic, limit, after)


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """One connection, three topics. Message shape: {id, topic, ts, data}.
    Optional client message: {"subscribe": ["trade.executed", ...]} to filter."""
    await ws.accept()
    wanted = set(TOPICS)
    q = bus.subscribe()
    try:
        await ws.send_json({"topic": "hello", "topics": list(TOPICS), "ts": None, "data": {"server": "spectraledger-ai-engine"}})
        for t in TOPICS:                                    # replay a little history so the UI is not empty on connect
            for e in bus.recent(t, 30 if t != "telemetry.raw" else 60):
                await ws.send_json(e)

        async def pump():
            while True:
                evt = await q.get()
                if evt["topic"] in wanted:
                    await ws.send_json(evt)

        async def listen():
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict) and isinstance(msg.get("subscribe"), list):
                    wanted.clear()
                    wanted.update(t for t in msg["subscribe"] if t in TOPICS)

        tasks = [asyncio.create_task(pump()), asyncio.create_task(listen())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")
