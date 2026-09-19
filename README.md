# TradingMaster

TradingMaster is a real-time cryptocurrency market-data service. It collects OHLCV candle data from Binance, Kraken, and Coinbase through CCXT Pro, publishes it to Kafka, persists it in PostgreSQL/TimescaleDB through Apache Flink, and exposes it through a FastAPI REST and WebSocket API.

For a non-technical overview of the business logic, use cases and improvement roadmap, see [docs/BUSINESS_SUMMARY.md](docs/BUSINESS_SUMMARY.md).

## Architecture

```text
Binance / Kraken / Coinbase -> CCXT Pro -> FastAPI producer -> Kafka -> Flink -> TimescaleDB
                                                                    └-> FastAPI WebSocket
```

Markets live in the database (`exchanges` + `symbols` tables), not in code. On first start the seeder adds about 50 pairs across the three exchanges, each at the `30s`, `1m`, `5m`, `1h` and `1d` intervals. Markets added through the API are collected within `PRODUCER_CONFIG_REFRESH_SECONDS` and stored by Flink without any restart. The producer creates one streaming task per configured exchange and reconnects after exchange errors.

**Unified market feed.** Every candle has the same format whatever the source exchange:
- `ticker` is the unified USD market (`BTC/USD`), and the exchange's own market (`BTC/USDT`) is kept in `source_ticker`.
- USDT/USDC prices are converted to USD at the live Kraken `USDT/USD` / `USDC/USD` rate (`fx_rate`).
- Prices and volume are exact decimals, sent as 8-decimal strings (`"65000.10000000"`).

## Project layout

```text
app/
├── main.py                       FastAPI application and lifecycle management
├── config.py                     Environment-based configuration
├── routers/market.py             REST and WebSocket market endpoints
├── models/                       SQLAlchemy ORM models and database helpers
├── schemas/                      Pydantic request and response schemas
├── helpers/                      Reusable application helpers
├── kafka/producer.py             CCXT Pro to Kafka producer (unified feed, hot-reloaded config)
├── kafka/fx_rates.py             Live USDT/USDC → USD conversion rates
├── flink_jobs/candle_builder.py  Kafka to TimescaleDB Flink job
├── flink_jobs/job_config.py      Flink job config/SQL builders (pure Python, unit-tested)
├── jobs/eod_archive.py           EOD archive job logic (candles -> candles_history + Parquet)
├── producer_runner.py            Standalone producer entry point
└── eod_runner.py                 Standalone EOD archive entry point (one-shot, external scheduler)
tests/                            Unit and API/integration tests
```

## Requirements

- Python 3.10+ recommended
- PostgreSQL or TimescaleDB
- Kafka broker
- Java 11+ and a compatible PyFlink installation for the Flink job
- Exchange WebSocket access through CCXT Pro

Public market streams do not require exchange API keys.

## Installation

```bash
python -m venv .env
source .env/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt
```

PyFlink is intentionally omitted from `requirements.txt`; install it separately according to the PyFlink/Python/Java versions in your deployment.

## Configuration

Create a local `.env` file or export environment variables:

```dotenv
TIMESCALE_URL=postgresql+asyncpg://user:password@localhost:5432/tradingmaster
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
PRODUCER_CONFIG_REFRESH_SECONDS=60   # how often the producer re-reads markets from the DB (0 = only at startup)
FX_REFERENCE_EXCHANGE=kraken         # source of the live USDT/USD and USDC/USD rates
FX_MAX_AGE_SECONDS=300               # older (or missing) rate → 1:1 peg fallback
BINANCE_API_KEY=
BINANCE_API_SECRET=
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
COINBASE_API_KEY=
COINBASE_API_SECRET=
AUTH_SECRET=
AUTH_TOKEN_LIFETIME_SECONDS=3600
```

`AUTH_SECRET` signs JWT access tokens (FastAPI Users) — set a real random value in every non-dev deployment; the built-in default is dev-only.

The markets to collect are not configured through environment variables. They're managed through `/api/v1/exchanges` (see [Markets](#markets)).

The API creates the `candles` table on startup. The Flink job additionally reads `TIMESCALE_JDBC_URL`, `TIMESCALE_USER`, and `TIMESCALE_PASS`.
These variables must be exported in the shell running the job; activating `env_flink` does not load `.env` automatically. When the job runs on the host with the included Docker Compose setup, use `jdbc:postgresql://localhost:5432/tradingmaster`. When it runs in a Compose container, use `jdbc:postgresql://postgres:5432/tradingmaster`.

## Running the API

Start Kafka and PostgreSQL/TimescaleDB, configure the environment, and run:

```bash
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; OpenAPI documentation is at `/docs`.

```bash
curl http://localhost:8000/health
```

The API starts the Kafka producer automatically. To run only the producer separately:

```bash
python -m app.producer_runner
```

## Auth

User accounts and JWT bearer auth are provided by [FastAPI Users](https://fastapi-users.github.io/fastapi-users/) (`app/auth/`), backed by a `users` table via `fastapi-users-db-sqlalchemy`. All read (`GET`) endpoints and the market WebSocket stream remain public; every mutating (`POST`/`PUT`) endpoint under `/api/v1/market`, `/api/v1/exchanges`, and the manual history-archive trigger requires a valid bearer token from an active user.

Register and log in:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"trader@example.com","password":"supersecret123"}'

curl -X POST http://localhost:8000/api/v1/auth/jwt/login \
  -d 'username=trader@example.com&password=supersecret123'
```

The login response's `access_token` is sent as `Authorization: Bearer <token>` on protected requests:

```bash
curl -X POST http://localhost:8000/api/v1/exchanges \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"name":"coinbase","method":"trades"}'
```

Other auth routes: `POST /api/v1/auth/jwt/logout`, `POST /api/v1/auth/forgot-password` / `POST /api/v1/auth/reset-password`, `POST /api/v1/auth/request-verify-token` / `POST /api/v1/auth/verify`, and `GET`/`PATCH /api/v1/users/me` (self-service profile). `/docs`'s Swagger UI has a built-in **Authorize** button that accepts the bearer token directly.

## API

### Get candles

```bash
curl 'http://localhost:8000/api/v1/market/candles/BTC%2FUSD?interval=5m&limit=100'
curl 'http://localhost:8000/api/v1/market/candles/BTC-USD?exchange=binance&interval=30s'
```

`GET /api/v1/market/candles/{ticker}` returns newest candles first. `exchange`, `interval` (`30s`, `1m`, `5m`, `1h`, `1d`) and `limit` are optional.
- Any spelling of a USD-equivalent market resolves to the unified ticker: `BTC/USD`, `BTC%2FUSDT`, `btc-usdc` and `BTCUSDT` all mean `BTC/USD`, across every exchange.
- Returns `422` for a non-USD quote (e.g. `ETH/BTC`) and `404` when no matching candles exist.

Response prices are strings with exactly 8 decimals, identical for every exchange:

```json
{"exchange": "binance", "ticker": "BTC/USD", "source_ticker": "BTC/USDT", "quote_currency": "USD",
 "fx_rate": "0.99973000", "interval": "1m", "timestamp": "2026-09-19T18:22:00",
 "open_price": "81457.00067000", "high_price": "81457.00067000", "low_price": "81444.00418000",
 "close_price": "81449.65265450", "volume": "6.25249000", "id": 1}
```

### Create a candle

```bash
curl -X POST http://localhost:8000/api/v1/market/candles \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"exchange":"binance","ticker":"BTC/USD","interval":"1m","open_price":65000,"high_price":65300,"low_price":64850,"close_price":65200,"volume":15.4}'
```

`POST /api/v1/market/candles` supports testing, manual insertion, and backfilling (requires an authenticated user — see [Auth](#auth)).
- The timestamp is optional and defaults to the current UTC time.
- Prices and volume must be non-negative numbers or numeric strings.
- The ticker must be quoted in USD, because a manual insert carries no FX rate.
- The interval must be one of the supported ones.

### Markets

```bash
# one ticker + interval
curl -X POST http://localhost:8000/api/v1/exchanges/1/symbols   -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json'   -d '{"ticker":"SOL/USDT","interval":"30s"}'

# many tickers × intervals at once — existing/clashing combinations are skipped and reported
curl -X POST http://localhost:8000/api/v1/exchanges/1/symbols/bulk   -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json'   -d '{"tickers":["SOL/USDT","XRP/USDT"],"intervals":["30s","1m","5m","1h","1d"]}'
```

Quotes must be USD, USDT or USDC, and intervals must be `30s`, `1m`, `5m`, `1h` or `1d`; anything else is a `422`. A duplicate returns `409`. So does a second market for the same coin and interval on one exchange (e.g. `BTC/USD` next to `BTC/USDT`), because both would publish the unified `BTC/USD`.

Where the exchange streams a timeframe natively (CCXT `exchange.timeframes`), it's used directly. Otherwise candles are built from the trade stream: `30s` on Binance/Kraken, and every interval on Coinbase.

### Stream live candles

```text
ws://localhost:8000/api/v1/market/ws/live/BTCUSD
ws://localhost:8000/api/v1/market/ws/live/BTCUSD?exchange=binance
```

Without `exchange`, the WebSocket subscribes to every enabled exchange that has an enabled market for that coin, according to the database. Messages are unified-format JSON candles, the same shape as the REST response minus `id`, plus `schema_version`. An unknown or unsupported market is closed with code `1008`.

## Kafka topics

Topics use `{exchange}.{UNIFIED_TICKER_WITHOUT_SLASH}.candles`, for example `binance.BTCUSD.candles` (fed by Binance's `BTC/USDT`) and `coinbase.BTCUSD.candles`. All intervals of a market share its topic, and each message carries its `interval`. Messages carry `"schema_version": 2`; the Flink job ignores older messages.

## Running the Flink job

After installing PyFlink and making the JDBC dependencies available to Flink:

The JDBC connector is modular in Flink 2.x. The `app/flink_jobs/jars/` directory must contain all of these files:

- `flink-connector-jdbc-core-4.0.0-2.0.jar`
- `flink-connector-jdbc-postgres-4.0.0-2.0.jar`
- `postgresql-42.7.3.jar`

The PostgreSQL dialect JAR is required in addition to the core JAR. Without it, Flink reports that only the Derby factory is available.

For a host-side run against the Compose database:

```bash
export TIMESCALE_JDBC_URL='jdbc:postgresql://localhost:5432/tradingmaster'
export TIMESCALE_USER='user'
export TIMESCALE_PASS='mysecretpassword'
env_flink/bin/python app/flink_jobs/candle_builder.py
```

Run it as a script, not with `python -m app.flink_jobs...`. Importing the `app` package pulls in the API's dependencies, which `env_flink` doesn't have.

For a job running inside the Compose network, set `TIMESCALE_JDBC_URL` to `jdbc:postgresql://postgres:5432/tradingmaster` instead.

How the job behaves:
- **Topics:** it reads the enabled exchanges from the `exchanges` table (with `psycopg`) and subscribes by topic pattern, e.g. `^(binance|coinbase|kraken)\.[A-Z0-9]+\.candles$`. Topic discovery runs every `FLINK_TOPIC_DISCOVERY_INTERVAL` (default `60s`), so pairs added through the API are stored without a restart. A new exchange needs a restart. If the DB can't be reached, it subscribes to every candle topic.
- **Resume where it stopped:** checkpointing is on (`FLINK_CHECKPOINT_INTERVAL`, default `30s`), and Kafka offsets are committed to the `flink-candle-builder` group on every checkpoint. On start the job continues from the committed offsets, or from the earliest retained offset for a new group or topic. Downtime is caught up as long as Kafka still retains the messages (7 days by default).
- **Writes:** records go through a batched JDBC sink with retries. It upserts on `(exchange, ticker, interval, timestamp)`, so replaying a message after a restart just rewrites the same row. Prices are cast from strings straight to `DECIMAL(28, 8)`.

Since `env_flink` is a separate virtualenv from `env/` (see Environments), also install the two lightweight packages the job's structured logging and trace-id extraction rely on:

```bash
source env_flink/bin/activate
pip install python-json-logger opentelemetry-api "psycopg[binary]"
```

`psycopg` is required: it's how the job reads the enabled exchanges from the database.

If they aren't importable, the job falls back to plain-text logging rather than failing — see `app/flink_jobs/candle_builder.py`'s import guard.

## Running the EOD archive job

The EOD archive job (candles -> candles_history + Parquet, `app/jobs/eod_archive.py`) runs as a **standalone, one-shot process** (`app/eod_runner.py`), not an in-process scheduler inside the API. It used to be an `asyncio` loop started in `app/main.py`'s lifespan — that meant a crashed or redeployed API process silently skipped that day's archive run. Driving it externally instead means it fires regardless of the API's own uptime.

```bash
source env/bin/activate
python -m app.eod_runner              # archives yesterday (UTC)
python -m app.eod_runner 2026-06-23   # backfill a specific date
```

Schedule it with cron, a systemd timer, or — in Kubernetes — the `eod-archive` CronJob in `k8s/base/eod-cronjob.yaml` (defaults to `30 23 * * *`, i.e. 23:30 UTC — 30 minutes before the day rolls over, giving `backoffLimit` retries room to finish before midnight; reuses the FastAPI image with `python -m app.eod_runner` as its command). The schedule is parametrized per environment via a Kustomize patch on `spec.schedule` rather than hardcoded — `k8s/overlays/local/eod-patch.yaml` overrides it to run every 10 minutes for local testing, and a production overlay can set its own cadence the same way. For ad-hoc runs without waiting on the schedule, `POST /api/v1/history/archive/{target_date}` (in `app/routers/history.py`) still triggers a background run through the API.

## Observability

```bash
docker compose up -d prometheus grafana jaeger loki promtail
```

- **Metrics**: Prometheus at `http://localhost:9090` scrapes `/metrics` on the FastAPI app (`prometheus-client`, see `app/metrics.py`) and Flink's own JVM-side Prometheus reporter on port 9250. Grafana at `http://localhost:3000` (`admin`/`admin` locally) auto-provisions both as datasources plus a starter "TradingMaster Overview" dashboard.
- **Tracing**: the FastAPI app and Kafka producer export spans via OpenTelemetry OTLP to Jaeger at `http://localhost:16686`. The Flink job cannot hold per-record spans (it runs Table API/SQL with no Python callback in the hot path) — instead it extracts the W3C `traceparent` header the producer attaches to each Kafka message and writes the trace id into `candles.trace_id`, so a persisted row can be correlated back to its producing trace with `SELECT * FROM candles WHERE trace_id = '<id>'`.
- **Logs**: every Python entrypoint (`app/main.py`, `app/producer_runner.py`, `app/flink_jobs/candle_builder.py`) emits structured JSON logs (`app/logging_config.py`), tagged with `trace_id`/`span_id` when an OTel span is active. Promtail ships them to Loki, browsable from Grafana Explore; a `trace_id` field in a log line links out to the matching Jaeger trace.
  Promtail (in this Compose setup) only tails **containers**, via the Docker socket. The FastAPI app and standalone producer run on the host by default (`uvicorn app.main:app`, `python -m app.producer_runner`), so their JSON logs land on your terminal / redirected file, not in Loki — only the containerized `flink` job's logs show up there locally. In Kubernetes this gap doesn't exist: Promtail runs as a DaemonSet and picks up every pod, FastAPI included.

## Testing

```bash
pytest
pytest tests/unit
pytest tests/test_market.py -k candles
```

Tests mock Kafka and exchange connections. API tests use temporary SQLite and do not require Kafka or TimescaleDB.

## Current limitations and operational notes

- **Existing databases need a one-off migration** for the multi-interval key and the unified feed (new columns, `NUMERIC(28,8)` prices, legacy tickers renamed to `BASE/USD` at a 1:1 rate). The script is idempotent:
  `psql "$DATABASE_URL" -f scripts/migrations/2026_09_unified_feed.sql`
- Only USD-equivalent markets (USD/USDT/USDC quotes) can be collected: the unified feed publishes every price in USD.
- If no fresh FX rate is available (startup, or a Kraken outage longer than `FX_MAX_AGE_SECONDS`), USDT/USDC prices are converted at the 1:1 peg. `fx_rate_fallback_total` counts these conversions.
- Running `app.producer_runner` alongside the API can create duplicate exchange streams.
- Database creation happens at startup; Alembic is installed but migrations are not configured.
- `candles.trace_id` (added for Jaeger correlation) only appears via `Base.metadata.create_all`, which creates missing tables but never alters existing ones — an existing local `candles` table needs a manual `ALTER TABLE candles ADD COLUMN trace_id VARCHAR(32)`, or drop the dev volume and let it rebuild.
- Jaeger and Loki run with in-memory/ephemeral storage in this compose/k8s setup — traces and logs don't survive a restart. Fine for local dev; production needs real storage backends (Elasticsearch/Cassandra for Jaeger, a persistent volume + retention config for Loki), not implemented here.
- Keep `.env`, credentials, passwords, and generated database files out of version control.
