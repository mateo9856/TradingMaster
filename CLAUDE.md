# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

TradingMaster is a real-time cryptocurrency market-data service. It collects OHLCV candle data from Binance, Kraken, and Coinbase via CCXT Pro, publishes it to Kafka, persists it in PostgreSQL/TimescaleDB through Apache Flink, and exposes it through a FastAPI REST/WebSocket API.

```
Binance / Kraken / Coinbase -> CCXT Pro -> FastAPI producer -> Kafka -> Flink -> TimescaleDB
                                                                    └-> FastAPI WebSocket
```

Default watched symbols are `BTC/USDT` and `ETH/USDT` at a `1m` interval. The producer runs one streaming task per configured exchange and reconnects after exchange errors.

## Commands

```bash
source .env/bin/activate            # or env/bin/activate — see Environments below
pip install -r requirements.txt
pip install -r requirements-test.txt

uvicorn app.main:app --reload       # run the API (starts the Kafka producer automatically)
python -m app.producer_runner       # run only the producer (don't run alongside the API — duplicate streams)
python -m app.flink_jobs.candle_builder   # run the Flink job (needs PyFlink + JARs, see below)

pytest                              # run all tests
pytest tests/unit                   # unit tests only (mocked Kafka/exchange clients)
pytest tests/test_market.py -k candles   # single test/pattern
```

API tests use a temporary SQLite DB and mock the Kafka producer; they don't need Kafka or TimescaleDB running. No linter/formatter is configured; follow existing style (four-space indent, `snake_case`, `PascalCase` classes, type hints on public functions, async for I/O).

## Environments

There are three Python venvs at the repo root: `env/` (API/app), `env_flink/` (PyFlink job — has its own package set, e.g. `avro`, `fastavro`), and `.env-old/` (stale, likely safe to ignore). PyFlink is intentionally excluded from `requirements.txt` because it must be pinned to match the installed Java/Python versions exactly.

Config is environment-variable based (`app/config.py`, loaded via `python-dotenv`). Key vars: `TIMESCALE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `WATCH_SYMBOLS`, `WATCH_EXCHANGES`, per-exchange `*_API_KEY`/`*_API_SECRET` (unneeded for public candle streams), `AUTH_SECRET`/`AUTH_TOKEN_LIFETIME_SECONDS` (JWT signing — override `AUTH_SECRET` outside dev). The Flink job additionally reads `TIMESCALE_JDBC_URL`, `TIMESCALE_USER`, `TIMESCALE_PASS` — these must be exported in the shell running the job; activating `env_flink` does not load `.env`. JDBC host differs by context: `localhost` when the job runs on the host against Compose, `postgres` when the job runs inside the Compose network.

## Architecture

- `app/main.py` — FastAPI app and lifespan management: creates DB tables on startup (no Alembic migrations wired up despite alembic being installed), seeds exchange/symbol config, starts the Kafka producer as a background task, and mounts the FastAPI Users auth/user routers. The EOD archive job is *not* run from here — it's a standalone process (`app/eod_runner.py`), see below.
- `app/auth/` — FastAPI Users wiring: `schemas.py` (UserRead/Create/Update), `db.py` (`get_user_db`, SQLAlchemy adapter), `manager.py` (`UserManager`, `get_user_manager`), `backend.py` (JWT bearer `AuthenticationBackend`), `users.py` (the `fastapi_users` instance plus `current_active_user`/`current_superuser` dependencies). `app/models/user.py` defines the `User` ORM table (UUID PK, from `SQLAlchemyBaseUserTableUUID`). All `GET` endpoints and the market WebSocket are public; every mutating endpoint in `routers/market.py`, `routers/exchanges.py`, and the history archive trigger requires `current_active_user`. Auth routes live under `/api/v1/auth/*` (register, JWT login/logout, password reset, email verify) and `/api/v1/users/*` (self-service profile + admin user management).
- `app/kafka/producer.py` — CCXT Pro → Kafka producer; one task per exchange in `WATCH_EXCHANGES`.
- `app/flink_jobs/candle_builder.py` — Kafka → TimescaleDB Flink job. Topic list is hard-coded (six topics for the default exchanges/symbols); writes through a batched JDBC sink with retries, using a declared `PRIMARY KEY (exchange, ticker, timestamp) NOT ENFORCED` on the sink table so the JDBC connector emits a real `ON CONFLICT ... DO UPDATE` upsert (matched by a `UniqueConstraint` on the `Candle` model). Requires JARs in `app/flink_jobs/jars/`: `flink-connector-jdbc-core-4.0.0-2.0.jar`, `flink-connector-jdbc-postgres-4.0.0-2.0.jar`, `postgresql-42.7.3.jar` (the JDBC connector is modular in Flink 2.x — missing the postgres dialect JAR causes Flink to fall back to only the Derby factory).
- `app/jobs/eod_archive.py` — daily end-of-day archive job (candle history → Parquet); run via the standalone `app/eod_runner.py` entrypoint or the manual `POST /api/v1/history/archive/{date}` trigger, not from an in-process scheduler.
- `app/routers/` — `market.py` (candle REST + WebSocket endpoints), `exchanges.py`, `history.py`.
- `app/models/` — SQLAlchemy async ORM models (`candle.py`, `candle_history.py`, `exchange.py`, `user.py`) plus `database.py` (engine/session/`Base`/`get_db`) and `seeder.py` (startup exchange/symbol seeding).
- `app/schemas/` — Pydantic request/response schemas, mirroring the models (auth schemas live in `app/auth/schemas.py` instead, per FastAPI Users convention).
- Kafka topics follow `{exchange}.{TICKER_WITHOUT_SLASHES}.candles`, e.g. `binance.BTCUSDT.candles`.
- WebSocket market stream: `ws://.../api/v1/market/ws/live/{TICKER}` (optional `?exchange=` filter; omitted = all configured exchanges). No auth on the WebSocket.

## Known gaps (don't assume these are fixed)

- Alembic is installed but not configured; schema changes rely on `Base.metadata.create_all` at startup, which never alters existing tables — the `candles` unique constraint (needed for the Flink upsert) and the `users` table both require a manual migration/`ALTER TABLE`/`CREATE TABLE` on any pre-existing database.
- Running `app.producer_runner` while the API is also running creates duplicate exchange streams (the API starts its own producer in `lifespan`).
- No email backend is wired up: FastAPI Users' `on_after_register`/`on_after_forgot_password`/`on_after_request_verify` hooks (`app/auth/manager.py`) only log — verification and password-reset tokens aren't actually emailed anywhere yet.
- All existing users can call every protected mutating endpoint (`is_active` only, no `is_superuser` gating) — there's no admin-vs-regular-user distinction on exchange/symbol management yet.

## Deployment

`docker-compose.yml` and `Dockerfile` cover local/Compose deployment; `k8s/base` + `k8s/overlays/{local,prod}` (Kustomize) cover Kubernetes. `scripts/download_flink_jars.sh` fetches the Flink JDBC connector JARs listed above.
