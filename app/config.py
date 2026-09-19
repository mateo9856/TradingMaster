from dotenv import load_dotenv
import os

load_dotenv()

# Database
TIMESCALE_URL: str = os.getenv("TIMESCALE_URL", "postgresql+asyncpg://user:mysecretpassword@localhost:5432/tradingmaster")

# Kafka
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# Markets (exchanges + trading pairs + intervals) are NOT configured here — they
# live in the `exchanges` / `symbols` tables (seeded by app/models/seeder.py,
# managed through /api/v1/exchanges). The producer re-reads them every
# PRODUCER_CONFIG_REFRESH_SECONDS, so API changes apply without a restart.
# 0 disables the refresh (config is read once at startup).
PRODUCER_CONFIG_REFRESH_SECONDS: int = int(os.getenv("PRODUCER_CONFIG_REFRESH_SECONDS", "60"))

# Unified feed: every price is published in USD. USDT/USDC-quoted markets are
# converted with live USDT/USD and USDC/USD rates from this exchange; a rate
# older than FX_MAX_AGE_SECONDS (or none yet) falls back to the 1:1 peg.
FX_REFERENCE_EXCHANGE: str = os.getenv("FX_REFERENCE_EXCHANGE", "kraken")
FX_MAX_AGE_SECONDS: int = int(os.getenv("FX_MAX_AGE_SECONDS", "300"))

# Exchange API keys — optional, only needed for private/trading endpoints
# Public candle/ticker streams work without keys
EXCHANGE_CREDENTIALS: dict = {
    "binance":  {"apiKey": os.getenv("BINANCE_API_KEY", ""),  "secret": os.getenv("BINANCE_API_SECRET", "")},
    "kraken":   {"apiKey": os.getenv("KRAKEN_API_KEY", ""),   "secret": os.getenv("KRAKEN_API_SECRET", "")},
    "coinbase": {"apiKey": os.getenv("COINBASE_API_KEY", ""), "secret": os.getenv("COINBASE_API_SECRET", "")},
}

# Observability — metrics
PROMETHEUS_METRICS_ENABLED: bool = os.getenv("PROMETHEUS_METRICS_ENABLED", "true").lower() == "true"

# Observability — tracing
OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower() == "true"
OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "tradingmaster-api")

# Observability — logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Auth — JWT signing for FastAPI Users. Override AUTH_SECRET in every real
# deployment; this default is dev-only and must never be used in production.
AUTH_SECRET: str = os.getenv("AUTH_SECRET", "dev-insecure-secret-change-me-in-every-real-deployment")
AUTH_TOKEN_LIFETIME_SECONDS: int = int(os.getenv("AUTH_TOKEN_LIFETIME_SECONDS", "3600"))