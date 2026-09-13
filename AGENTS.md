# Repository Guidelines

## Project Structure & Module Organization

- `app/` contains the application package: `main.py` (FastAPI app + lifespan — creates DB tables via `create_all`, seeds exchange/symbol config, starts the Kafka producer background task, mounts the auth/user routers); `config.py` (env-var config via `python-dotenv`); `metrics.py` (Prometheus collectors), `tracing.py` (OTel setup), `logging_config.py` (JSON logging) — observability modules; `auth/` (FastAPI Users wiring — `schemas.py`, `db.py`, `manager.py`, `backend.py` for the JWT bearer backend, `users.py` for the `fastapi_users` instance and `current_active_user`/`current_superuser` dependencies); `routers/` (`market.py`, `exchanges.py`, `history.py`); `models/` (SQLAlchemy async ORM models — `candle.py`, `candle_history.py`, `exchange.py`, `user.py` — plus `database.py` and `seeder.py`); `schemas/` (Pydantic request/response schemas for the app's own resources; auth schemas live in `app/auth/schemas.py`); `helpers/` (small reusable utilities, e.g. `time.py`); `kafka/producer.py` (CCXT Pro → Kafka streaming); `flink_jobs/candle_builder.py` (Kafka → TimescaleDB PyFlink job); `jobs/eod_archive.py` (EOD archive logic); `producer_runner.py` and `eod_runner.py` (standalone entrypoints — see Commands).
- Auth: all `GET` endpoints and the market WebSocket are public; every mutating endpoint in `market.py`/`exchanges.py` plus the history archive trigger requires a bearer-token-authenticated active user (`Depends(current_active_user)`). Auth/user-management routes are under `/api/v1/auth/*` and `/api/v1/users/*` — see README's Auth section.
- `tests/` contains async API/integration tests (`test_market.py`, `test_exchanges_history.py`), `tests/unit/` (mocked Kafka/exchange clients), and `tests/integration/` (real, unmocked job runs against SQLite). Shared fixtures are in `tests/conftest.py` (sets `OTEL_ENABLED=false` before app import).
- `observability/` holds Prometheus/Grafana/Promtail config for the Compose stack. `k8s/base` + `k8s/overlays/{local,prod}` (Kustomize) cover Kubernetes, including `eod-cronjob.yaml`. `scripts/download_flink_jars.sh` fetches the Flink JDBC connector JARs.
- `requirements.txt` lists API/app Python dependencies (PyFlink is deliberately excluded — see Commands). Do not commit `.env`, generated DB files, or production data.

## Build, Test, and Development Commands

Three separate venvs exist at the repo root: `env/` (API/app), `env_flink/` (PyFlink job — its own package set), and `.env-old/` (stale, ignore).

```bash
source env/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt

uvicorn app.main:app --reload --host 0.0.0.0   # run the API (also starts the Kafka producer)
python -m app.producer_runner                  # producer only — don't run alongside the API (duplicate streams)
python -m app.eod_runner [YYYY-MM-DD]           # one-shot EOD archive job (external scheduler; not run in-process anymore)

pytest                                   # all tests
pytest tests/unit                        # unit tests only (mocked Kafka/exchange clients)
pytest tests/test_market.py -k candles   # single test/pattern
```

For the Flink job (needs its own venv and downloaded JARs, and does not load `.env`):

```bash
source env_flink/bin/activate
python -m app.flink_jobs.candle_builder
```

API tests use a temporary SQLite DB and mock the Kafka producer — Kafka/TimescaleDB are not required to run `pytest`. Exercising live streaming or persistence does require Kafka/PostgreSQL, configured via environment variables (see Security & Configuration Tips).

## Coding Style & Naming Conventions

Four-space indentation, `snake_case` for functions/variables/modules, `PascalCase` for classes, uppercase for configuration constants. Keep type hints on public functions and follow the existing async style for I/O. No formatter or linter is configured — match surrounding file style.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio` (`pytest.ini`: `asyncio_mode = auto`). Name files `test_*.py`, functions `test_*`, classes `Test*`. Unit tests mock Kafka/exchange clients; integration tests under `tests/integration/` run real job logic against a seeded SQLite session with nothing mocked internally. Add regression coverage for new endpoints, validation rules, and stream/job transformations.

## Commit & Pull Request Guidelines

Existing history uses short, imperative, capitalized subject lines describing the change (e.g. `Fix postgres flink connection`, `Add EOD archive, candle history + tests`, `Resolve import table problem`) — follow that pattern, one logical change per commit. Pull requests should explain the behavior change, list validation commands run (e.g. `pytest -q`), call out required environment/infrastructure changes (new env vars, Docker/K8s manifests, migrations), and include API examples when the interface changes.

## Security & Configuration Tips

Keep `.env`, exchange API keys, database passwords, Kafka credentials, and `AUTH_SECRET` local — public candle streams don't need exchange keys. Key env vars: `TIMESCALE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `WATCH_SYMBOLS`, `WATCH_EXCHANGES`, `PROMETHEUS_METRICS_ENABLED`, `OTEL_ENABLED`/`OTEL_EXPORTER_OTLP_ENDPOINT`, `LOG_LEVEL`, `AUTH_SECRET`/`AUTH_TOKEN_LIFETIME_SECONDS` (JWT signing for FastAPI Users — the checked-in default is dev-only, override it everywhere else). The Flink job additionally needs `TIMESCALE_JDBC_URL`, `TIMESCALE_USER`, `TIMESCALE_PASS` exported directly in its shell (activating `env_flink` does not load `.env`). Never include secrets or generated database files in patches.

## Known Gaps (don't assume these are fixed)

- Alembic is installed but not configured; schema changes rely on `Base.metadata.create_all` at startup, which never alters existing tables — new columns/constraints (e.g. `candles.trace_id`, the `candles` unique constraint, the new `users` table) require a manual migration on any pre-existing local/dev database.
- Running `app.producer_runner` while the API is also running creates duplicate exchange streams (the API starts its own producer in `lifespan`).
- Jaeger and Loki use in-memory/ephemeral storage in the current Compose/K8s setup — fine for dev, needs real storage backends before production.
- FastAPI Users' `on_after_register`/`on_after_forgot_password`/`on_after_request_verify` hooks (`app/auth/manager.py`) only log — no email backend is wired up, so verification/password-reset tokens aren't actually delivered anywhere yet.
- Auth only checks `is_active`, not `is_superuser` — there's no admin-vs-regular-user distinction on exchange/symbol management yet; any registered user can manage them.
