"""In-process pub/sub: this IS the 'Kafka replacement' (ring buffers + WebSocket fan-out).

Three topics: telemetry.raw, trade.executed, agent.decision. publish() is callable from any
thread (the agent loop runs in a worker thread); WebSocket delivery hops back onto the
asyncio loop with call_soon_threadsafe.
"""
import asyncio
import itertools
import threading
from collections import deque
from datetime import datetime, timezone

TOPICS = ("telemetry.raw", "trade.executed", "agent.decision")
_BUF = {"telemetry.raw": 600, "trade.executed": 300, "agent.decision": 300}


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._buffers = {t: deque(maxlen=_BUF[t]) for t in TOPICS}
        self._subs = set()          # asyncio.Queue objects, one per WebSocket
        self._loop = None

    def bind_loop(self, loop):
        self._loop = loop

    def publish(self, topic, data):
        if topic not in self._buffers:
            raise ValueError(f"unknown topic {topic}")
        evt = {"id": next(self._seq), "topic": topic,
               "ts": datetime.now(timezone.utc).isoformat(), "data": data}
        with self._lock:
            self._buffers[topic].append(evt)
        if self._loop is not None and self._subs:
            self._loop.call_soon_threadsafe(self._fanout, evt)
        return evt

    def _fanout(self, evt):
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()          # slow client: drop its oldest event, never block the engine
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(evt)

    def recent(self, topic, limit=50, after=0):
        with self._lock:
            items = [e for e in self._buffers[topic] if e["id"] > after]
        return items[-limit:]

    def subscribe(self):
        q = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q):
        self._subs.discard(q)


bus = EventBus()
