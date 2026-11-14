# Repository Guidelines

## Project Structure & Module Organization

- `src/app/` contains the application package: `main.py` (compatibility entrypoint), `bootstrap/` (factory, schema-checking lifespan, middleware, router registration, SPA serving), `paths.py` (deployment assets); `config.py` (env-var config via `python-dotenv`); `metrics.py` (Prometheus collectors), `tracing.py` (OTel setup), `logging_config.py` (JSON logging) — observability modules; `auth/` (FastAPI Users wiring — `schemas.py`, `db.py`, `manager.py`, `backend.py` for the JWT bearer backend, `users.py` for the `fastapi_users` instance and `current_active_user`/`current_superuser` dependencies); `routers/` (`market.py`, `exchanges.py`, `history.py`); `models/` (SQLAlchemy async ORM models — `candle.py`, `candle_history.py`, `exchange.py`, `user.py` — plus `database.py` and `seeder.py`); `schemas/` (Pydantic request/response schemas for the app's own resources; auth schemas live in `src/app/auth/schemas.py`); `helpers/` (small reusable utilities — `time.py`, and the unified-feed rules: `intervals.py` for supported intervals, `markets.py` for unified `BASE/USD` tickers, `prices.py` for 8-decimal prices); `kafka/producer.py` (CCXT Pro → Kafka streaming, config hot-reloaded from the DB) + `kafka/fx_rates.py` (live USDT/USDC → USD rates); `flink_jobs/candle_builder.py` (Kafka → TimescaleDB PyFlink job) + `flink_jobs/job_config.py` (its pure-Python config/SQL builders, unit-tested from `env/`); `jobs/eod_archive.py` (EOD archive logic); `producer_runner.py` and `eod_runner.py` (standalone entrypoints — see Commands).
- Auth has two backends on the same versioned JWT (`src/app/auth/backend.py`): an http-only `SameSite=strict` cookie for the browser UI and bearer tokens for API clients. Logout increments the user's `auth_version`, revoking all sessions for that user. `src/app/auth/csrf.py` rejects cookie-authenticated writes without `X-Requested-With`; bearer requests are untouched. Market reads and the market WebSocket are public; exchange, symbol, and instrument catalogue mutations require an active superuser. Other protected actions require an active user. Registration remains open and new users are not administrators.
- `frontend/` is the React + Vite + TypeScript UI: `src/app/` owns shell/routing/providers; `src/features/{auth,markets,history,system,trading}/` owns domain pages, components, hooks, API functions, types and tests; `src/shared/` owns HTTP transport, primitives, formatting, i18n/currency infrastructure and SEO; `src/locales/` owns translations; `src/test/` owns the common harness. Shared modules must not import feature/app implementations. `frontend/dist/` is served by FastAPI; the standalone nginx variant remains supported.
- `tests/` contains async API/integration tests (`test_market.py`, `test_exchanges_history.py`), `tests/unit/` (mocked Kafka/exchange clients), and `tests/integration/` (real, unmocked job runs against SQLite). Shared fixtures are in `tests/conftest.py` (sets `OTEL_ENABLED=false` before app import).
- `observability/` holds Prometheus/Grafana/Promtail config for the Compose stack. `k8s/base` + `k8s/overlays/{local,prod}` (Kustomize) cover Kubernetes, including `eod-cronjob.yaml`. `scripts/download_flink_jars.sh` fetches the Flink JDBC connector JARs.
- `requirements.txt` lists API/app Python dependencies (PyFlink is deliberately excluded — see Commands). Do not commit `.env`, generated DB files, or production data.

## Build, Test, and Development Commands

Three separate venvs exist at the repo root: `env/` (API/app), `env_flink/` (PyFlink job — its own package set), and `.env-old/` (stale, ignore).

```bash
source env/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install --no-deps -e .

uvicorn app.main:app --reload --host 0.0.0.0   # run the API
python -m app.producer_runner                  # run the dedicated singleton collector
python -m app.eod_runner [YYYY-MM-DD]           # one-shot EOD archive job (external scheduler; not run in-process anymore)

pytest                                   # all tests
pytest tests/unit                        # unit tests only (mocked Kafka/exchange clients)
pytest tests/test_market.py -k candles   # single test/pattern
```

Front-end (Node 22, its own dependency tree under `frontend/`):

```bash
cd frontend
npm install
npm run dev        # :5173, proxies /api and the WebSocket to the API on :8000
npm run test:run   # Vitest — mocked API, no backend needed
npm run build      # frontend/dist, which FastAPI then serves at /
```

For the Flink job (needs its own venv and downloaded JARs, and does not load `.env`):

```bash
source env_flink/bin/activate
python src/app/flink_jobs/candle_builder.py   # as a script: `python -m app...` would import the API's deps
```

API tests use a temporary SQLite DB and mock the Kafka producer — Kafka/TimescaleDB are not required to run `pytest`. Exercising live streaming or persistence does require Kafka/PostgreSQL, configured via environment variables (see Security & Configuration Tips).

## Coding Style & Naming Conventions

Four-space indentation, `snake_case` for functions/variables/modules, `PascalCase` for classes, uppercase for configuration constants. Keep type hints on public functions and follow the existing async style for I/O. Ruff (`env/bin/python -m ruff check .`) checks correctness, unused imports and import order; ESLint (`npm --prefix frontend run lint`) checks correctness, React Hooks and shared dependency direction. Match surrounding file style; no wholesale formatting.

## Testing Guidelines

Front-end tests use Vitest + Testing Library with MSW for the API and a fake WebSocket (`src/test/fake-websocket.ts`); screen tests stub the chart component, whose data conversion is unit-tested separately. Backend tests use `pytest` with `pytest-asyncio` (`pytest.ini`: `asyncio_mode = auto`). Name files `test_*.py`, functions `test_*`, classes `Test*`. Unit tests mock Kafka/exchange clients; integration tests under `tests/integration/` run real job logic against a seeded SQLite session with nothing mocked internally. Add regression coverage for new endpoints, validation rules, and stream/job transformations.

## Commit & Pull Request Guidelines

Existing history uses short, imperative, capitalized subject lines describing the change (e.g. `Fix postgres flink connection`, `Add EOD archive, candle history + tests`, `Resolve import table problem`) — follow that pattern, one logical change per commit. Pull requests should explain the behavior change, list validation commands run (e.g. `pytest -q`), call out required environment/infrastructure changes (new env vars, Docker/K8s manifests, migrations), and include API examples when the interface changes.

## Security & Configuration Tips

Keep `.env`, exchange API keys, database passwords, Kafka credentials, and `AUTH_SECRET` local — public candle streams don't need exchange keys. Key env vars include `TIMESCALE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SECURITY_PROTOCOL`, `CORS_ALLOW_ORIGINS`, `AUTH_COOKIE_NAME`/`AUTH_COOKIE_SECURE`, `PRODUCER_CONFIG_REFRESH_SECONDS`, observability settings, `AUTH_SECRET`/`AUTH_TOKEN_LIFETIME_SECONDS`, `APP_ENV`, `DB_SCHEMA_CHECK`, `DOCS_ENABLED`, `TRUST_PROXY_HEADERS`, `RATE_LIMIT_BACKEND`/`RATE_LIMIT_REDIS_URL`, `WS_*`, and `PARQUET_BASE_DIR` — see `.env.example`. Production requires TLS for PostgreSQL, Kafka, and Redis rate limiting. Markets live in the `exchanges`/`symbols` tables. The Flink job additionally needs `TIMESCALE_JDBC_URL`, `TIMESCALE_USER`, `TIMESCALE_PASS` and its Kafka security settings exported directly in its shell; activating `env_flink` does not load `.env`. Never include secrets or generated database files in patches.

## Known Gaps (don't assume these are fixed)

- The live-stream consumer hub remains per API process; each API replica opens its own Kafka consumer. HTTP and WebSocket rate limits use shared Redis in production, while local development defaults to in-memory limits.
- TimescaleDB is **not** actually enabled — plain `postgres:16`, no hypertable, compression or retention policy.
- Kubernetes API and archive jobs share a PVC for Parquet output. Production needs a durable `ReadWriteMany` storage class; local Kubernetes uses a `ReadWriteOnce` patch.
- Local Compose Kafka and PostgreSQL use plaintext; production requires TLS for PostgreSQL/Kafka and TLS Redis for shared rate limits. External endpoints and certificates still need cluster validation.
- Logout revokes every cookie and bearer token for that user through the per-user `auth_version` field.
- `NetworkPolicy` objects exist but are only enforced if the cluster's CNI implements them.
- Jaeger and Loki use in-memory/ephemeral storage in the current Compose/K8s setup — fine for dev, needs real storage backends before production.
- FastAPI Users' `on_after_register`/`on_after_forgot_password`/`on_after_request_verify` hooks (`src/app/auth/manager.py`) only log — no email backend is wired up, so verification/password-reset tokens aren't actually delivered anywhere yet.
- The UI has no exchange/symbol management screen yet — markets are added through the API only.
- Registration is open and accounts are active immediately; email verification is not required because the configured hooks do not deliver email. New accounts are regular users; administrators must be promoted through an authorized operator workflow.
- Representative production performance baselines still need to be collected against real PostgreSQL, Kafka, and exchange traffic before performance tuning.
