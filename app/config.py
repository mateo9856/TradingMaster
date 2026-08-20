from dotenv import load_dotenv
import os

load_dotenv()

# Database
TIMESCALE_URL: str = os.getenv("TIMESCALE_URL", "postgresql+asyncpg://user:mysecretpassword@localhost:5432/tradingmaster")

# Kafka
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# Symbols and exchanges to watch
WATCH_SYMBOLS: list[str] = os.getenv("WATCH_SYMBOLS", "BTC/USDT,ETH/USDT").split(",")
WATCH_EXCHANGES: list[str] = os.getenv("WATCH_EXCHANGES", "binance,kraken,coinbase").split(",")

# Exchange API keys — optional, only needed for private/trading endpoints
# Public candle/ticker streams work without keys
EXCHANGE_CREDENTIALS: dict = {
    "binance":  {"apiKey": os.getenv("BINANCE_API_KEY", ""),  "secret": os.getenv("BINANCE_API_SECRET", "")},
    "kraken":   {"apiKey": os.getenv("KRAKEN_API_KEY", ""),   "secret": os.getenv("KRAKEN_API_SECRET", "")},
    "coinbase": {"apiKey": os.getenv("COINBASE_API_KEY", ""), "secret": os.getenv("COINBASE_API_SECRET", "")},
}