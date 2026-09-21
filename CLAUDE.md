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

Config is environment-variable based (`app/config.py`, loaded via `python-dotenv`). Key vars: `TIMESCALE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `PRODUCER_CONFIG_REFRESH_SECONDS`, `FX_REFERENCE_EXCHANGE`/`FX_MAX_AGE_SECONDS`, per-exchange `*_API_KEY`/`*_API_SECRET` (unneeded for public candle streams), `AUTH_SECRET`/`AUTH_TOKEN_LIFETIME_SECONDS` (JWT signing — override `AUTH_SECRET` outside dev), `AUTH_COOKIE_NAME`/`AUTH_COOKIE_SECURE` (session cookie; `secure` defaults to false so local http works, and must be true in production). The Flink job additionally reads `TIMESCALE_JDBC_URL`, `TIMESCALE_USER`, `TIMESCALE_PASS` (plus optional `FLINK_CHECKPOINT_INTERVAL`, `FLINK_TOPIC_DISCOVERY_INTERVAL`, `FLINK_CHECKPOINT_DIR`) — these must be exported in the shell running the job; activating `env_flink` does not load `.env`. JDBC host differs by context: `localhost` when the job runs on the host against Compose, `postgres` when the job runs inside the Compose network.

## Architecture

- `app/main.py` — FastAPI app and lifespan management: creates DB tables on startup (no Alembic migrations wired up despite alembic being installed), seeds exchange/symbol config, starts the Kafka producer as a background task, and mounts the FastAPI Users auth/user routers. The EOD archive job is *not* run from here — it's a standalone process (`app/eod_runner.py`), see below.
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
- WebSocket market stream: `ws://.../api/v1/market/ws/live/{TICKER}`, with an optional `?exchange=` filter. Topics come from the DB (`_resolve_topics`), and an unknown market is closed with code 1008. No auth on the WebSocket.
- Symbols API: `POST /api/v1/exchanges/{id}/symbols` and `/symbols/bulk`.
  - Only USD/USDT/USDC quotes and the supported intervals are accepted; anything else is a 422.
  - A duplicate, or a second market feeding the same unified ticker on one exchange, is a 409.

## Known gaps (don't assume these are fixed)

- Alembic is installed but not configured; schema changes rely on `Base.metadata.create_all` at startup, which never alters existing tables — the `users` table requires a manual `CREATE TABLE` on any pre-existing database. The multi-interval `candles` unique key, the unified-feed columns and the `NUMERIC(28,8)` prices ship as the idempotent `scripts/migrations/2026_09_unified_feed.sql`, which must be run once on existing DBs.
- Running `app.producer_runner` while the API is also running creates duplicate exchange streams (the API starts its own producer in `lifespan`).
- No email backend is wired up: FastAPI Users' `on_after_register`/`on_after_forgot_password`/`on_after_request_verify` hooks (`app/auth/manager.py`) only log — verification and password-reset tokens aren't actually emailed anywhere yet.
- All existing users can call every protected mutating endpoint (`is_active` only, no `is_superuser` gating) — there's no admin-vs-regular-user distinction on exchange/symbol management yet.

## Deployment

`docker-compose.yml` and `Dockerfile` cover local/Compose deployment; `k8s/base` + `k8s/overlays/{local,prod}` (Kustomize) cover Kubernetes. `scripts/download_flink_jars.sh` fetches the Flink JDBC connector JARs listed above.
