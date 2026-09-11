# TradingMaster

TradingMaster is a real-time cryptocurrency market-data service. It collects OHLCV candle data from Binance, Kraken, and Coinbase through CCXT Pro, publishes it to Kafka, persists it in PostgreSQL/TimescaleDB through Apache Flink, and exposes it through a FastAPI REST and WebSocket API.

## Architecture

```text
Binance / Kraken / Coinbase -> CCXT Pro -> FastAPI producer -> Kafka -> Flink -> TimescaleDB
                                                                    └-> FastAPI WebSocket
```

The default watched symbols are `BTC/USDT` and `ETH/USDT`, with a `1m` candle interval. The producer creates one streaming task per configured exchange and reconnects after exchange errors.

## Project layout

```text
app/
├── main.py                       FastAPI application and lifecycle management
├── config.py                     Environment-based configuration
├── routers/market.py             REST and WebSocket market endpoints
├── models/                       SQLAlchemy ORM models and database helpers
├── schemas/                      Pydantic request and response schemas
├── helpers/                      Reusable application helpers
├── kafka/producer.py             CCXT Pro to Kafka producer
├── flink_jobs/candle_builder.py  Kafka to TimescaleDB Flink job
└── producer_runner.py            Standalone producer entry point
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
WATCH_SYMBOLS=BTC/USDT,ETH/USDT
WATCH_EXCHANGES=binance,kraken,coinbase
BINANCE_API_KEY=
BINANCE_API_SECRET=
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
COINBASE_API_KEY=
COINBASE_API_SECRET=
```

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

## API

### Get candles

```bash
curl 'http://localhost:8000/api/v1/market/candles/BTC%2FUSDT?exchange=binance&interval=1m&limit=100'
```

`GET /api/v1/market/candles/{ticker}` returns newest candles first. `exchange`, `interval`, and `limit` are optional. A URL-encoded ticker is supported; `404` is returned when no matching candles exist.

### Create a candle

```bash
curl -X POST http://localhost:8000/api/v1/market/candles \
  -H 'Content-Type: application/json' \
  -d '{"exchange":"binance","ticker":"BTC/USDT","interval":"1m","open_price":65000,"high_price":65300,"low_price":64850,"close_price":65200,"volume":15.4}'
```

`POST /api/v1/market/candles` supports testing, manual insertion, and backfilling. The timestamp is optional and defaults to the current UTC time. Prices and volume must be non-negative.

### Stream live candles

```text
ws://localhost:8000/api/v1/market/ws/live/BTCUSDT
ws://localhost:8000/api/v1/market/ws/live/BTCUSDT?exchange=binance
```

Without `exchange`, the WebSocket subscribes to all configured exchanges. Messages are JSON candle objects.

## Kafka topics

Topics use `{exchange}.{TICKER_WITHOUT_SLASHES}.candles`, for example `binance.BTCUSDT.candles` and `kraken.ETHUSDT.candles`.

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
python -m app.flink_jobs.candle_builder
```

For a job running inside the Compose network, set `TIMESCALE_JDBC_URL` to `jdbc:postgresql://postgres:5432/tradingmaster` instead.

The current job consumes six hard-coded topics for the default exchanges and symbols and writes records through a batched JDBC sink with retries.

Since `env_flink` is a separate virtualenv from `env/` (see Environments), also install the two lightweight packages the job's structured logging and trace-id extraction rely on:

```bash
source env_flink/bin/activate
pip install python-json-logger opentelemetry-api
```

If they aren't importable, the job falls back to plain-text logging rather than failing — see `app/flink_jobs/candle_builder.py`'s import guard.

## Observability

```bash
docker compose up -d prometheus grafana jaeger loki promtail
```

- **Metrics**: Prometheus at `http://localhost:9090` scrapes `/metrics` on the FastAPI app (`prometheus-client`, see `app/metrics.py`) and Flink's own JVM-side Prometheus reporter on port 9250. Grafana at `http://localhost:3000` (`admin`/`admin` locally) auto-provisions both as datasources plus a starter "TradingMaster Overview" dashboard.
- **Tracing**: the FastAPI app and Kafka producer export spans via OpenTelemetry OTLP to Jaeger at `http://localhost:16686`. The Flink job cannot hold per-record spans (it runs Table API/SQL with no Python callback in the hot path) — instead it extracts the W3C `traceparent` header the producer attaches to each Kafka message and writes the trace id into `candles.trace_id`, so a persisted row can be correlated back to its producing trace with `SELECT * FROM candles WHERE trace_id = '<id>'`.
- **Logs**: every Python entrypoint (`app/main.py`, `app/producer_runner.py`, `app/flink_jobs/candle_builder.py`) emits structured JSON logs (`app/logging_config.py`), tagged with `trace_id`/`span_id` when an OTel span is active. Promtail ships them to Loki, browsable from Grafana Explore; a `trace_id` field in a log line links out to the matching Jaeger trace.

## Testing

```bash
pytest
pytest tests/unit
pytest tests/test_market.py -k candles
```

Tests mock Kafka and exchange connections. API tests use temporary SQLite and do not require Kafka or TimescaleDB.

## Current limitations and operational notes

- The Flink SQL uses `ON CONFLICT (exchange, ticker, timestamp)`, but the SQLAlchemy model has no matching unique constraint. Add one before relying on Flink upserts.
- The Flink topic list is hard-coded in `app/flink_jobs/candle_builder.py`.
- Running `app.producer_runner` alongside the API can create duplicate exchange streams.
- Database creation happens at startup; Alembic is installed but migrations are not configured.
- `candles.trace_id` (added for Jaeger correlation) only appears via `Base.metadata.create_all`, which creates missing tables but never alters existing ones — an existing local `candles` table needs a manual `ALTER TABLE candles ADD COLUMN trace_id VARCHAR(32)`, or drop the dev volume and let it rebuild.
- Jaeger and Loki run with in-memory/ephemeral storage in this compose/k8s setup — traces and logs don't survive a restart. Fine for local dev; production needs real storage backends (Elasticsearch/Cassandra for Jaeger, a persistent volume + retention config for Loki), not implemented here.
- Keep `.env`, credentials, passwords, and generated database files out of version control.
