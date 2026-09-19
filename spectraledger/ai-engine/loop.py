"""THE AUTONOMOUS LOOP - runs inside the server process from startup with zero external calls.

Two asyncio tasks (started in main.py's lifespan):
  telemetry_task : every TELEMETRY_INTERVAL_S advance the simulated clock and broadcast telemetry.raw
  agent_task     : every AGENT_INTERVAL_S run every slice as seller then buyer, rest unmatched
                   orders in the book, clear matches, sweep the book (fills human orders), fire webhooks.
The agent tick runs in a worker thread (LightGBM + LangGraph are CPU-bound) so the event loop,
WebSockets and HTTP stay responsive.
"""
import asyncio
import logging
import time

import agents
import clearing
import config
import telemetry
from events import bus
from orderbook import book
from state import live

log = logging.getLogger("loop")
stats = {"telemetry_ticks": 0, "agent_ticks": 0, "last_agent_tick_ms": None, "last_agent_tick_at": None,
         "running": False}


def run_tick():
    t0 = time.time()
    live.expire_leases()
    for role in ("seller", "buyer"):                       # sellers first so buyers see freshly listed asks
        for sl in telemetry.SLICES:
            try:
                agents.run_agent(sl["id"], role, commit=True)
            except Exception:
                log.exception("agent failed for %s/%s", sl["id"], role)
    for fill in book.sweep():                              # clears crossed manual orders too
        clearing.clear_trade(fill)
    stats["agent_ticks"] += 1
    stats["last_agent_tick_ms"] = round((time.time() - t0) * 1000, 1)
    stats["last_agent_tick_at"] = time.time()


async def telemetry_task():
    while True:
        for smp in live.advance():
            bus.publish("telemetry.raw", smp)
        stats["telemetry_ticks"] += 1
        await asyncio.sleep(config.TELEMETRY_INTERVAL_S)


async def agent_task():
    stats["running"] = True
    while True:
        try:
            await asyncio.to_thread(run_tick)
        except Exception:
            log.exception("agent tick failed")
        await asyncio.sleep(config.AGENT_INTERVAL_S)
