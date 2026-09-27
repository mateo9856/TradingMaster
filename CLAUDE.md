# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

TradingMaster is a real-time cryptocurrency market-data service. It collects OHLCV candle data from Binance, Kraken, and Coinbase via CCXT Pro, publishes it to Kafka, persists it in PostgreSQL/TimescaleDB through Apache Flink, and exposes it through a FastAPI REST/WebSocket API.

```
Binance / Kraken / Coinbase -> CCXT Pro -> FastAPI producer -> Kafka -> Flink -> TimescaleDB
                                                                    └-> FastAPI WebSocket -> React UI (frontend/)
```

Markets (exchange + ticker + interval) live in the DB (`exchanges`/`symbols` tables), not in env config. The seeder adds about 50 default pairs at `30s`/`1m`/`5m`/`1h`/`1d`. The producer runs one streaming task per configured exchange, reconnects after exchange errors, and re-reads the DB every `PRODUCER_CONFIG_REFRESH_SECONDS` (default 60), so markets added through the API are picked up without a restart.

**Unified market feed:** every candle has one format for all exchanges.
- `ticker` is the unified `BASE/USD` market, and the exchange's own market is in `source_ticker`.
- USDT/USDC prices are converted to USD with live Kraken rates (`fx_rate`); the 1:1 peg is the fallback.
- Prices and volume are exact decimals: `NUMERIC(28,8)` in the DB and 8-decimal strings in Kafka/REST/WS.
- Messages carry `schema_version: 2`, and Flink stores nothing else.
- The rules live in `app/helpers/{intervals,markets,prices}.py`.

## Commands

```bash
source .env/bin/activate            # or env/bin/activate — see Environments below
pip install -r requirements.txt
pip install -r requirements-test.txt

alembic upgrade head                # apply DB migrations — the API refuses to start otherwise
uvicorn app.main:app --reload       # run the API (starts the Kafka producer automatically)
python -m app.producer_runner       # run only the producer (don't run alongside the API — duplicate streams)
env_flink/bin/python app/flink_jobs/candle_builder.py   # Flink job — run as a script, not `-m app...` (needs PyFlink + JARs + psycopg)

cd frontend && npm install          # UI deps (Node 22)
cd frontend && npm run dev          # UI at :5173, proxies /api + WebSocket to :8000
cd frontend && npm run build        # bundle into frontend/dist — FastAPI then serves it at /
cd frontend && npm run test:run     # UI tests (Vitest + Testing Library + MSW)

pytest                              # run all backend tests
pytest tests/unit                   # unit tests only (mocked Kafka/exchange clients)
pytest tests/test_market.py -k candles   # single test/pattern
```

API tests use a temporary SQLite DB and mock the Kafka producer; they don't need Kafka or TimescaleDB running. No linter/formatter is configured; follow existing style (four-space indent, `snake_case`, `PascalCase` classes, type hints on public functions, async for I/O).

## Environments

There are three Python venvs at the repo root: `env/` (API/app), `env_flink/` (PyFlink job — has its own package set, e.g. `avro`, `fastavro`), and `.env-old/` (stale, likely safe to ignore). PyFlink is intentionally excluded from `requirements.txt` because it must be pinned to match the installed Java/Python versions exactly.

Config is environment-variable based (`app/config.py`, loaded via `python-dotenv`). Key vars: `TIMESCALE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `PRODUCER_CONFIG_REFRESH_SECONDS`, `FX_REFERENCE_EXCHANGE`/`FX_MAX_AGE_SECONDS`, per-exchange `*_API_KEY`/`*_API_SECRET` (unneeded for public candle streams), `AUTH_SECRET`/`AUTH_TOKEN_LIFETIME_SECONDS` (JWT signing), `AUTH_COOKIE_NAME`/`AUTH_COOKIE_SECURE` (session cookie), `APP_ENV` (`production` enables `validate_config()`, which refuses to start on the dev `AUTH_SECRET`, an empty one, `AUTH_COOKIE_SECURE=false` or an unsafe CORS list — all of these used to fail open), `DB_SCHEMA_CHECK`, `DOCS_ENABLED`, `TRUST_PROXY_HEADERS`, the `RATE_LIMIT_*` and `WS_*` caps, and `PARQUET_BASE_DIR`. `.env.example` documents all of them. The Flink job additionally reads `TIMESCALE_JDBC_URL`, `TIMESCALE_USER`, `TIMESCALE_PASS` (plus optional `FLINK_CHECKPOINT_INTERVAL`, `FLINK_TOPIC_DISCOVERY_INTERVAL`, `FLINK_CHECKPOINT_DIR`) — these must be exported in the shell running the job; activating `env_flink` does not load `.env`. JDBC host differs by context: `localhost` when the job runs on the host against Compose, `postgres` when the job runs inside the Compose network.

## Architecture

- `app/main.py` — FastAPI app and lifespan management: **verifies** the DB is at the migrations' head (`app/models/schema_check.py`) and refuses to start otherwise — it no longer creates tables — then seeds exchange/symbol config, starts the Kafka producer as a background task, and mounts the FastAPI Users auth/user routers. Middleware order matters and is documented inline: outside in, security headers → CORS → metrics → rate limit → CSRF → router. CORS must stay outside CSRF or a 403 carries no CORS headers. The EOD archive job is *not* run from here — it's a standalone process (`app/eod_runner.py`), see below.
- `app/auth/` — FastAPI Users wiring: `schemas.py` (UserRead/Create/Update), `db.py` (`get_user_db`, SQLAlchemy adapter), `manager.py` (`UserManager`, `get_user_manager`), `backend.py` (**two** `AuthenticationBackend`s over one JWT strategy: `cookie_backend` — http-only, `SameSite=strict`, what the UI uses — and `auth_backend`, the bearer transport for API clients), `users.py` (the `fastapi_users` instance registered with both, plus `current_active_user`/`current_superuser`), `csrf.py` (HTTP middleware: a request carrying the auth cookie must send `X-Requested-With` on non-safe methods, else 403; cookie-less bearer requests pass through). `app/models/user.py` defines the `User` ORM table (UUID PK, from `SQLAlchemyBaseUserTableUUID`). All `GET` endpoints and the market WebSocket are public; every mutating endpoint in `routers/market.py`, `routers/exchanges.py`, and the history archive trigger requires `current_active_user`. Auth routes live under `/api/v1/auth/*`: `cookie/login`+`cookie/logout` (browser, 204 + Set-Cookie), `jwt/login`+`jwt/logout` (bearer), plus register, password reset and email verify and `/api/v1/users/*` (self-service profile + admin user management).
- `app/kafka/producer.py`: CCXT Pro → Kafka producer, one task per enabled exchange.
  - Config comes from the DB and is hot-reloaded by `_reconcile_streams`.
  - A timeframe the exchange streams natively (`exchange.timeframes`) is used directly. Anything else is built from trades: `30s` everywhere, and every interval for `method="trades"` (Coinbase).
  - `build_unified_payload` produces the unified message.
  - `app/kafka/fx_rates.py` keeps the live USDT/USDC → USD rates.
- `app/flink_jobs/candle_builder.py`: Kafka → TimescaleDB Flink job, wired from pure-Python builders in `job_config.py` (unit-tested from `env/`).
  - Topics: a pattern built from the enabled exchanges in the DB (read with psycopg), plus partition discovery, so new pairs are stored without a restart.
  - Resume: checkpointing is on and Kafka offsets are committed on each checkpoint. The job starts from `group-offsets` (falling back to `earliest`), so downtime is caught up.
  - Writes: a batched JDBC sink with retries. The declared `PRIMARY KEY (exchange, ticker, interval, timestamp) NOT ENFORCED` makes the connector emit `ON CONFLICT ... DO UPDATE`, matching the `Candle` `UniqueConstraint`.
  - Flink 2.3 needs `table.exec.sink.require-on-conflict=false` for this insert-only → PK sink, which is set in `build_runtime_config`. Requires JARs in `app/flink_jobs/jars/`: `flink-connector-jdbc-core-4.0.0-2.0.jar`, `flink-connector-jdbc-postgres-4.0.0-2.0.jar`, `postgresql-42.7.3.jar` (the JDBC connector is modular in Flink 2.x — missing the postgres dialect JAR causes Flink to fall back to only the Derby factory).
- `app/jobs/eod_archive.py` — daily end-of-day archive job (candle history → Parquet); run via the standalone `app/eod_runner.py` entrypoint or the manual `POST /api/v1/history/archive/{date}` trigger, not from an in-process scheduler.
  - **Idempotent.** `candles_history` has a unique key on `(exchange, ticker, interval, timestamp)` and the job inserts `ON CONFLICT DO NOTHING` (`app/helpers/upsert.py`), so a re-run, a CronJob retry and the local overlay's 10-minute schedule are all no-ops. Counting uses `RETURNING`, not `rowcount` — PostgreSQL reports `-1` for an executemany insert.
  - Streams in `CHUNK_SIZE` batches; a PostgreSQL advisory lock on a dedicated connection (not the working session, which commits per chunk) stops concurrent runs.
  - Retention cleanup only deletes hot candles that are actually present in history, so a failed archive no longer destroys the day anyway.
  - `--replace` refuses to run when the day's source candles are gone, because it would delete the archive and have nothing to rebuild from.
  - Every run writes a `job_runs` row; the API exports it to Prometheus and serves it at `GET /api/v1/history/archive/runs`. The CronJob pod has no `/metrics` endpoint, so this is the only way the scheduled path is observable.
- `app/kafka/stream_hub.py` — one Kafka consumer per *topic*, shared by every WebSocket subscriber and reference-counted. The live stream's cost scales with markets watched, not with viewers. Subscribers have bounded queues that drop oldest.
- `app/middleware/rate_limit.py` — in-process sliding-window limits (read/write/auth/ws/archive buckets). Per-pod, so with N replicas the effective limit is ~N×. `X-Forwarded-For` is honoured only when `TRUST_PROXY_HEADERS=true`.
- `app/middleware/security_headers.py` — CSP and friends, with a relaxed policy for `/docs` (Swagger loads from a CDN).
- `migrations/` + `alembic.ini` — Alembic. `0001_baseline` is guarded by `has_table` so a database built by the old `create_all` path converges with a plain `alembic upgrade head`; `0002_legacy_alignment` ports the old one-off SQL script plus the two gaps it never covered. Later revisions are ordinary unguarded migrations.
- `app/routers/` — `market.py` (candle REST + WebSocket endpoints), `exchanges.py`, `history.py`.
- `app/models/` — SQLAlchemy async ORM models (`candle.py`, `candle_history.py`, `exchange.py`, `user.py`) plus `database.py` (engine/session/`Base`/`get_db`) and `seeder.py` (startup exchange/symbol seeding).
- `app/schemas/` — Pydantic request/response schemas, mirroring the models (auth schemas live in `app/auth/schemas.py` instead, per FastAPI Users convention).
- `frontend/` — React + Vite + TypeScript MVP UI (Tailwind v4, shadcn-style primitives in `src/components/ui/`).
  - Session: an http-only cookie, so nothing is stored in the page. `auth.tsx` probes `GET /users/me` on mount to see whether a session exists; the client sends `credentials: "same-origin"` plus the `X-Requested-With` CSRF header on every request.
  - `src/lib/` — `api.ts` (typed client, `ApiError`/`NetworkError`), `format.ts`/`ticker.ts`/`chart-data.ts` (the unified format in the browser), `auth.tsx`.
  - `src/hooks/useLiveCandles.ts` — the market WebSocket; close code 1008 means "no such market" and is not retried.
  - Screens: Live (chart + raw feed), History (+ archive trigger), System (health/metrics), Login/Profile.
  - Tests mock the API with MSW and the socket with `src/test/fake-websocket.ts`; the chart is stubbed in screen tests (its conversion logic is covered in `src/lib/chart-data.test.ts`).
  - Served two ways: Vite dev proxy, or built into `frontend/dist` and served by FastAPI. `frontend/Dockerfile` + `k8s/base/frontend.yaml` cover the standalone nginx variant.
- `GET /api/v1/market/markets` lists collected markets (unified ticker → exchanges + intervals); it backs the UI's picker and avoids duplicating the unified-ticker rules in TypeScript.
- `app/main.py` serves `frontend/dist` at `/` when it exists (SPA fallback for client-side routes), and `/metrics` is a **route, not a mount** — a mount only answers `/metrics/`, and the SPA catch-all would swallow the bare path Prometheus scrapes.
- Kafka topics follow `{exchange}.{UNIFIED_TICKER_WITHOUT_SLASH}.candles`, e.g. `binance.BTCUSD.candles` (fed by Binance `BTC/USDT`). All intervals of a market share its topic.
- WebSocket market stream: `ws://.../api/v1/market/ws/live/{TICKER}`, with optional `?exchange=` and `?interval=` filters. Topics come from the DB (`_resolve_topics`, now filtered in SQL rather than by scanning every enabled symbol per connection). Close codes: **1008** unknown market (the UI treats this as permanent and does not retry — see `useLiveCandles.ts`), **1013** at capacity or rate-limited (temporary). Subscribers share consumers via the stream hub, and the server sends `{"type": "heartbeat"}` on a quiet market so half-open sockets can be reclaimed; the UI ignores those frames. No auth on the WebSocket.
- Symbols API: `POST /api/v1/exchanges/{id}/symbols` and `/symbols/bulk`.
  - Only USD/USDT/USDC quotes and the supported intervals are accepted; anything else is a 422.
  - A duplicate, or a second market feeding the same unified ticker on one exchange, is a 409.
- `ExchangeCreate.name` is validated against `^[a-z0-9_]{2,32}$` **and** ccxt's own exchange list, and `method` is a `Literal`. The name is not just a label: it becomes `getattr(ccxtpro, name)`, a Kafka topic segment, and part of the Flink job's topic-pattern *inside a SQL string literal* (`re.escape` does not escape `'`).
- Every list endpoint takes capped `limit`/`offset`; `limit` used to be an unbounded bare `int` on `/market/candles` and `/history/{ticker}`. History also caps the date span at `HISTORY_MAX_RANGE_DAYS`.
- `http_requests_total` is labelled by the **matched route template**, not the raw path — labelling by raw path let any client mint unbounded Prometheus series.
- Alert rules live in `observability/prometheus/rules/tradingmaster.yml` (validate with `promtool check config`), delivered via an Alertmanager with a deliberately no-op receiver.

## Known gaps (don't assume these are fixed)

- **The producer runs inside the API lifespan** while the prod overlay sets `replicas: 3` — three copies of every exchange stream and every Kafka message. `app/producer_runner.py` exists as a standalone entrypoint but has no Deployment of its own. This is the highest-value open item (finding A04-5 in `docs/SECURITY_AUDIT.md`).
- Running `app.producer_runner` while the API is also running creates duplicate exchange streams, for the same reason.
- **No admin role.** `current_superuser` is defined in `app/auth/users.py` and used on no endpoint; every active user can pause exchanges, bulk-add markets, insert candles and trigger archives. Mutating endpoints now log the acting user id, so the actions are at least attributable.
- **Open registration.** Accounts are `is_active=True` immediately and `current_active_user` does not require `is_verified`. Registration is rate-limited but the authorisation model is unchanged.
- No email backend: FastAPI Users' `on_after_*` hooks only log, so password-reset and verification tokens are generated but never delivered.
- **TimescaleDB is not actually enabled** — it is plain `postgres:16`, with no hypertable, compression or retention policy anywhere.
- Parquet archives go to `PARQUET_BASE_DIR` (default `data/`), which in Kubernetes is the Job pod's ephemeral disk — **the files are lost when the Job ends.** Point it at a persistent volume or object storage.
- Rate limiting and the stream hub are **per process**, so limits multiply by replica count.
- Kafka is plaintext (no SASL/TLS) and the Flink job's psycopg connection sets no `sslmode`.
- JWTs cannot be revoked — logout clears the cookie but the token stays valid for its lifetime (1h default) in either transport.
- `NetworkPolicy` objects exist but are only enforced if the cluster's CNI implements them; a clean apply is not proof of enforcement.

## Deployment

`docker-compose.yml` and `Dockerfile` cover local/Compose deployment; `k8s/base` + `k8s/overlays/{local,prod}` (Kustomize) cover Kubernetes. `scripts/download_flink_jars.sh` fetches the Flink JDBC connector JARs listed above.
