"""Async, non-blocking outbound webhook -> Java ledger. Failures are logged, never raised."""
import asyncio
import logging

import httpx

import config

log = logging.getLogger("webhook")
_client = None
_loop = None
_stats = {"sent_ok": 0, "failed": 0, "last_error": None}


def bind_loop(loop):
    global _loop, _client
    _loop = loop
    _client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))


async def close():
    if _client:
        await _client.aclose()


def stats():
    return dict(_stats, target=config.BACKEND_TRADE_WEBHOOK)


async def _post(event: dict):
    headers = {"X-Webhook-Secret": config.WEBHOOK_SECRET, "Content-Type": "application/json"}
    for attempt in range(config.WEBHOOK_RETRIES + 1):
        try:
            r = await _client.post(config.BACKEND_TRADE_WEBHOOK, json=event, headers=headers)
            if r.status_code < 300:
                _stats["sent_ok"] += 1
                return
            _stats["last_error"] = f"HTTP {r.status_code}: {r.text[:120]}"
            if 400 <= r.status_code < 500:      # a 4xx will not fix itself on retry
                break
        except Exception as exc:                 # backend down / refused / timeout
            _stats["last_error"] = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(0.5 * (attempt + 1))
    _stats["failed"] += 1
    log.warning("trade webhook for %s failed (%s); ledger will not have this trade", event.get("trade_id"), _stats["last_error"])


def fire(event: dict):
    """Callable from any thread. Schedules the POST on the main loop and returns immediately."""
    if _loop is None or _client is None:
        return
    asyncio.run_coroutine_threadsafe(_post(event), _loop)
