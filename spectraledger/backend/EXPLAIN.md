# Backend file guide (for explaining to judges)

**One-sentence architecture:** the Python AI engine *decides* (forecast, price, match); this Java service *settles* — it receives a trade that has already cleared and moves the money like a bank vault: atomically, exactly once, and with an immutable audit trail.

**Request flow to remember:** `AI engine → POST /api/trades/execute` → `WebhookSecretFilter` (checks the secret) → `TradeController` → `TradeIngestService` (creates accounts if new, then calls…) → `SettlementService` (one database transaction: lock accounts, check for duplicate, compute money, write Trade + 3 LedgerEntry rows, update balances).

All Java lives under `src/main/java/com/spectraledger/ledger/`.

---

## Root

### `LedgerApplication`
The Spring Boot entry point: `main()` starts the embedded web server on port 8080 and scans the package tree for components. `@ConfigurationPropertiesScan` makes Spring turn the `spectraledger:` block of `application.yml` into the typed `LedgerProperties` object. Every other class is discovered automatically from here.

## `config/` — wiring and security

### `LedgerProperties`
A Java `record` bound to the `spectraledger:` section of `application.yml`: webhook secret, platform fee rate (2%), opening account balance, and CORS origins. It exists so settings are typed and in one place instead of scattered `@Value` strings — and so switching the fee to 3% is a one-line config change, not a code change.

### `WebhookSecretFilter`
A servlet filter that runs before the controller and rejects `POST /api/trades/execute` with `401` unless the `X-Webhook-Secret` header matches the configured secret. It compares with `MessageDigest.isEqual` (constant time) so an attacker can't guess the secret by measuring response time. This is deliberately the whole "auth story" — enough to show real intent without a login system.

### `SecurityConfig`
Configures Spring Security: CSRF off (stateless JSON API with no cookies), no sessions, every route open *except* that the webhook filter guards the settlement endpoint. It also defines the CORS rules so the browser dashboard (served from another port or from a file) may call the API. Without this class Spring Security would lock everything behind a generated password.

## `entity/` — the database tables (JPA maps each class to a table)

### `Enterprise`
A company that owns slices: `id`, unique `name`, generated `api_key`, `created_at`. The API key is the single credential the spec asks for; it is created automatically the first time an enterprise appears in a trade.

### `SliceAccount`
The money account for one network slice: `slice_id` (unique), `balance` (`BigDecimal`, never `double`), and a link to its `Enterprise`. It carries an `@Version` field — an optimistic-locking safety net that makes Hibernate refuse a stale write — on top of the pessimistic lock `SettlementService` takes. `debit()` and `credit()` are the only ways the balance changes.

### `Trade`
One settled trade: the AI engine's `trade_id` (with a `UNIQUE` constraint — the database-level backstop for idempotency), buyer/seller slice ids, price, quantity, gross amount, platform fee, net-to-seller, `executed_at` (when the engine cleared it) and `settled_at` (when we booked it), plus a status. The ledger recomputes the money fields itself rather than trusting the sender's arithmetic.

### `LedgerEntry`
One immutable line in the double-entry journal, pointing at a `Trade` and a `SliceAccount`, with a type and amount. Rows are only ever inserted — never updated or deleted — which is what makes the trail auditable. Every trade writes exactly three: buyer `DEBIT`, seller `CREDIT`, and a `FEE`.

### `TradeStatus`
A tiny enum (`SETTLED`, `FAILED`). Present so the schema can express a failed settlement later without a migration; today every persisted trade is `SETTLED` because failures roll back completely.

### `EntryType`
The enum `DEBIT`, `CREDIT`, `FEE` used on ledger lines. Convention: buyer is debited the gross amount; seller is credited the gross amount and then charged the FEE line, so the seller nets `gross − fee` and platform revenue is simply the sum of FEE lines.

## `repository/` — database access (Spring Data writes the SQL from method names)

### `EnterpriseRepository`
Finds an enterprise by name so provisioning can reuse it instead of creating duplicates.

### `SliceAccountRepository`
Looks up accounts by slice id and — most importantly — provides `lockById`, a `SELECT … FOR UPDATE` on one account row (plus `findIdBySliceId`, which reads only the id so no stale copy of the balance is loaded before locking). The settlement code locks the two accounts of a trade one after the other in ascending id order. Always locking in the same order means two concurrent trades can never each hold one account while waiting for the other (a deadlock), and it serializes trades that touch the same slice so balances can't be corrupted.

### `TradeRepository`
Finds trades by `trade_id` (the idempotency check), pages them newest-first for the dashboard, and sums fees/volume/Mbps for the revenue endpoint. SQL `SUM` over no rows returns NULL, so default methods convert that to zero.

### `LedgerEntryRepository`
Fetches the entries of one trade or one account's history, and sums amounts by type/account. Those sums power the self-audit (`/api/ledger/verify`): recompute every balance from the journal and compare with the stored balance.

## `dto/` — the shapes that cross the wire (never expose entities directly)

### `TradeExecutedEvent`
The incoming webhook body, matching the AI engine's `TradeExecutedEvent` in snake_case. Validation annotations (`@NotBlank`, `@DecimalMin`, `@Digits`) reject a malformed payload with a clear `400` before any business code runs. Extra fields the engine sends (event type, fee rate…) are ignored.

### `Views`
A holder for the small response records: settlement result, trade view, ledger-entry view, page wrapper, account view, revenue summary, integrity report, error body. Java records give immutable DTOs with no boilerplate, and grouping them keeps the package tidy.

## `exception/` — turning failures into clean HTTP answers

### `ApiException`
A runtime exception carrying an HTTP status, thrown for deliberate client errors (unknown trade id → 404, buyer equals seller → 422).

### `GlobalExceptionHandler`
A `@RestControllerAdvice` that converts every exception into a JSON error: validation problems and unparseable JSON become `400`, wrong content-type `415`, unknown routes `404`, and anything unexpected becomes a logged `500` with a generic message. This is what guarantees a malformed webhook never produces a raw stack-trace 500.

## `service/` — the business logic

### `AccountProvisioningService`
Creates the `Enterprise` and `SliceAccount` (with the opening balance) the first time a slice appears, in its **own** small transaction (`REQUIRES_NEW`). Doing this separately means an account-creation race between two simultaneous webhooks can be retried without disturbing the money-moving transaction.

### `SettlementService`
The vault. One `@Transactional` method: lock both accounts → check the trade id hasn't been settled → compute gross/fee/net with `BigDecimal` → debit buyer, credit seller → save the trade and three journal lines. Because it is a single transaction, either everything commits or nothing does (ACID). The duplicate check happens *after* taking the locks, so a retried webhook that raced with the original always sees the original's committed result — and is answered "duplicate" instead of settling twice.

### `TradeIngestService`
The front door for webhooks. It is intentionally *not* transactional: it ensures both accounts exist, calls the settlement transaction, and if the database's `UNIQUE(trade_id)` constraint ever fires it reports the trade as an already-settled duplicate. Splitting these concerns gives each failure mode one clear owner.

### `QueryService`
All read-only queries for the dashboard: paged trades, one trade with its journal lines, balances, account history, the revenue summary — plus `verify()`, which recomputes every account balance from the journal and confirms fees and the double-entry totals reconcile. Marked `readOnly` so the database can optimize.

## `controller/` — the REST endpoints

### `TradeController`
`POST /api/trades/execute` (the idempotent webhook receiver), `GET /api/trades` (paginated, newest first) and `GET /api/trades/{trade_id}` (trade plus its ledger entries). Controllers stay thin: parse, validate, delegate.

### `AccountController`
`GET /api/accounts` (all accounts), `GET /api/accounts/{slice_id}/balance`, and `GET /api/accounts/{slice_id}/history`. These drive the dashboard's "look up a slice" box.

### `SystemController`
`GET /api/health` (used to confirm the service is up before opening the UI), `GET /api/revenue/summary` (total fees, volume, trade count — the Java-side source of truth), and `GET /api/ledger/verify` (the tamper-evidence self-audit).

## Test

### `ConcurrentSettlementTest` (`src/test/java/...`)
The manual concurrency-safety proof (`mvn test`). Test 1 fires 300 trades from 16 threads at once against just three accounts and asserts every final balance equals the single-threaded arithmetic exactly, that there are exactly 900 journal rows, and that the self-audit passes. Test 2 delivers the *same* trade 40 times concurrently and asserts exactly one settles. If the locking were removed, test 1 would show lost updates.

---

### Talking points if a judge asks
* **"Why H2?"** Zero setup and file-persisted; moving to PostgreSQL is a config change (`spring.datasource.*` + swap the dependency) — the JPA code doesn't change.
* **"What if the webhook is retried?"** Idempotent on `trade_id`: lock, check, and a UNIQUE constraint as the last line of defence.
* **"Why BigDecimal?"** Floating point can't represent money exactly; every amount is scale-4 `BigDecimal` with explicit rounding.
* **"Why does the ledger recompute the fee?"** A ledger never trusts a sender's arithmetic; it reconciles and logs mismatches.
