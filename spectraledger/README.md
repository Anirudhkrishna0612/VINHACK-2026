# SpectraLedger — Capacity Marketplace

An autonomous B2B marketplace where enterprises lease **unused capacity within private 5G network slices they are already authorized to operate**. Buyers get *instant burst capacity when they need it*; owners of idle capacity recover revenue as a secondary benefit.

> **Framing:** this system does **not** trade spectrum licenses. It resells unused *capacity* inside a slice each enterprise already operates — structurally like reselling wholesale bandwidth or cloud compute. All copy, endpoints and entities use "capacity", "bandwidth lease", "slice capacity" and "trade".

## The three parts

| Part | Tech | Port | Role |
|---|---|---|---|
| `ai-engine/` | Python, FastAPI, LangGraph, LightGBM | 8000 | Forecasts demand, prices capacity, runs autonomous buyer/seller agents, keeps the order book, clears trades, streams events, fires a webhook per trade |
| `backend/` | Java 21, Spring Boot, JPA, H2 (file) | 8080 | Tamper-proof ledger: idempotently settles every cleared trade with double-entry journal lines, exposes balances/revenue |
| `frontend/` | Plain HTML/CSS/JS | 5500 (any static server, or open the file) | Ledger & revenue dashboard, live market, order book with manual order form, negotiation demo |

No Docker, no Kafka (WebSocket + polling fallback *is* the pub/sub layer), no CI/CD.

## Start order (three steps — order matters)

**1. Start the AI engine first** — it must be generating telemetry before anything connects to it.

```bash
./start-ai-engine.sh          # creates .venv, installs deps, then: python main.py
```
First start trains the LightGBM models (~5–10 s) and saves them to `ai-engine/models/`.

**2. Start the backend second** — the AI engine's webhook target defaults to `http://localhost:8080/api/trades/execute` (env `BACKEND_TRADE_WEBHOOK`) and the shared secret to `spectraledger-demo-secret` on both sides (env `WEBHOOK_SECRET` in the engine, `SPECTRALEDGER_WEBHOOK_SECRET` in the backend). If you change either, set it on **both** processes.

```bash
./start-backend.sh            # = cd backend && mvn spring-boot:run
```

**3. Open the frontend last**, once both health checks pass:

```bash
curl -s localhost:8000/health     # {"status":"ok", ... "loop": {"agent_ticks": N ...}}
curl -s localhost:8080/api/health # {"status":"ok","service":"spectraledger-ledger"}
cd frontend && python3 -m http.server 5500   # then browse to http://localhost:5500
# (or just double-click frontend/index.html — CORS is open for the demo)
```

Backend URLs live **only** in `frontend/config.js`.

If the backend is down when a trade clears, the engine logs a warning and keeps trading (the webhook fails silently by design); start order matters only because trades cleared while the ledger is down are not replayed.

## What to expect
* Within one ~8 s tick of AI-engine startup every slice with safe surplus lists an ask — with zero API calls.
* Trades clear autonomously as slices hit their (simulated) peak; a simulated day passes in ~10 real minutes. `SIM_START_HOUR` (default 11) sets where the clock starts so activity begins quickly.
* Fees: 2% of gross, mirrored in `ai-engine/config.py` (`PLATFORM_FEE_RATE`) and `backend/src/main/resources/application.yml`.

## Guardrails you can tweak live (env vars for the AI engine)
`SLA_CONFIDENCE_THRESHOLD` (0.50) · `SAFETY_CEILING` (0.90) · `BUYER_TRIGGER_UTIL` (0.74) · `BUYER_TARGET_UTIL` (0.66) · `MIN_LOT_MBPS` (10) · `AGENT_INTERVAL_S` (8) · `PLATFORM_FEE_RATE` (0.02). `GET /config` shows the active values. Example: `SLA_CONFIDENCE_THRESHOLD=0.75 python main.py` makes sellers refuse to list far more often (great for showing the SLA-risk gate).

## Key endpoints
AI engine: `POST /forecast`, `POST /price`, `POST /agent/evaluate`, `POST /agent/negotiate`, `GET|POST /orderbook[/orders]`, `DELETE /orderbook/orders/{id}`, `GET /revenue/summary`, `GET /revenue/trades`, `GET /events/{topic}`, `WS /ws/stream`, `GET /health`, `GET /slices`, `GET /config`.
Backend: `POST /api/trades/execute` (needs `X-Webhook-Secret`), `GET /api/trades`, `GET /api/trades/{trade_id}`, `GET /api/accounts[/{slice_id}/balance|history]`, `GET /api/revenue/summary`, `GET /api/ledger/verify`, `GET /api/health`.

## Proving the ledger (backend)
```bash
cd backend && mvn test     # ConcurrentSettlementTest: 300 concurrent trades on 3 accounts + 40 duplicate webhook deliveries
```
Plain-English tour of every Java class: `backend/EXPLAIN.md`.

## Manual test cheat-sheet
```bash
# settle one trade by hand (idempotent — run it twice, second reply has "duplicate": true)
curl -s -XPOST localhost:8080/api/trades/execute -H 'content-type: application/json' -H 'X-Webhook-Secret: spectraledger-demo-secret' \
  -d '{"trade_id":"T-manual-1","buyer_slice_id":"slice-ai-01","seller_slice_id":"slice-mmtc-01","price":0.25,"quantity_mbps":40}'
curl -s -XPOST localhost:8080/api/trades/execute -H 'content-type: application/json' -H 'X-Webhook-Secret: wrong' -d '{}'   # 401
curl -s -XPOST localhost:8080/api/trades/execute -H 'content-type: application/json' -H 'X-Webhook-Secret: spectraledger-demo-secret' -d '{bad'   # 400, never 500
```
