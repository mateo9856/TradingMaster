import json
import os
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    KafkaSource,
    KafkaOffsetsInitializer,
)
from pyflink.datastream.connectors.jdbc import (
    JdbcSink,
    JdbcConnectionOptions,
    JdbcExecutionOptions,
)
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.typeinfo import Types
from pyflink.datastream.functions import MapFunction

KAFKA_SERVERS  = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TIMESCALE_JDBC = os.getenv(
    "TIMESCALE_JDBC_URL",
    "jdbc:postgresql://localhost:5432/tradingmaster"
)
TIMESCALE_USER = os.getenv("TIMESCALE_USER", "user")
TIMESCALE_PASS = os.getenv("TIMESCALE_PASS", "password")

# Kafka topics to consume — one per exchange+ticker combination
KAFKA_TOPICS = [
    "binance.BTCUSDT.candles",
    "binance.ETHUSDT.candles",
    "kraken.BTCUSDT.candles",
    "kraken.ETHUSDT.candles",
    "coinbase.BTCUSDT.candles",
    "coinbase.ETHUSDT.candles",
]

# SQL upsert — inserts new candles, skips duplicates by exchange+ticker+timestamp
INSERT_SQL = """
    INSERT INTO candles
        (exchange, ticker, interval, timestamp, open_price, high_price, low_price, close_price, volume)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (exchange, ticker, timestamp) DO UPDATE SET
        open_price  = EXCLUDED.open_price,
        high_price  = EXCLUDED.high_price,
        low_price   = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        volume      = EXCLUDED.volume
"""


class ParseCandle(MapFunction):
    """Deserializes JSON message from Kafka into a typed tuple."""

    def map(self, value: str):
        d = json.loads(value)
        return (
            d["exchange"],
            d["ticker"],
            d.get("interval", "1m"),
            d["timestamp"],      # ISO string — cast to TIMESTAMP in PostgreSQL
            float(d["open_price"]),
            float(d["high_price"]),
            float(d["low_price"]),
            float(d["close_price"]),
            float(d["volume"]),
        )


def main():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(2)  # increase for production

    # ── Kafka Source ──────────────────────────────────────────────────────────
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_SERVERS)
        .set_topics(*KAFKA_TOPICS)
        .set_group_id("flink-candle-builder")
        .set_starting_offsets(KafkaOffsetsInitializer.latest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    stream = env.from_source(
        source=source,
        watermark_strategy=None,
        source_name="KafkaCandleSource",
    )

    # ── Parse JSON → typed tuple ──────────────────────────────────────────────
    parsed = stream.map(
        ParseCandle(),
        output_type=Types.TUPLE([
            Types.STRING(),  # exchange
            Types.STRING(),  # ticker
            Types.STRING(),  # interval
            Types.STRING(),  # timestamp
            Types.DOUBLE(),  # open_price
            Types.DOUBLE(),  # high_price
            Types.DOUBLE(),  # low_price
            Types.DOUBLE(),  # close_price
            Types.DOUBLE(),  # volume
        ]),
    )

    # ── JDBC Sink → TimescaleDB ───────────────────────────────────────────────
    jdbc_sink = JdbcSink.sink(
        sql=INSERT_SQL,
        type_info=Types.TUPLE([
            Types.STRING(), Types.STRING(), Types.STRING(), Types.STRING(),
            Types.DOUBLE(), Types.DOUBLE(), Types.DOUBLE(), Types.DOUBLE(), Types.DOUBLE(),
        ]),
        connection_options=(
            JdbcConnectionOptions.JdbcConnectionOptionsBuilder()
            .with_url(TIMESCALE_JDBC)
            .with_driver_name("org.postgresql.Driver")
            .with_user_name(TIMESCALE_USER)
            .with_password(TIMESCALE_PASS)
            .build()
        ),
        execution_options=(
            JdbcExecutionOptions.builder()
            .with_batch_interval_ms(500)   # flush every 500ms
            .with_batch_size(100)          # or every 100 rows
            .with_max_retries(3)
            .build()
        ),
    )

    parsed.add_sink(jdbc_sink)

    env.execute("TradingMaster — Candle Builder")


if __name__ == "__main__":
    main()