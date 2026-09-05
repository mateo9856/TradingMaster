"""
PyFlink Candle Builder Job — Table API version

Reads raw candle JSON from Kafka topics and writes to PostgreSQL.

This version uses PyFlink Table API with SQL DDL which is the recommended
approach for PyFlink — no manual JAR classpath management needed.

Required JARs (download once, see INSTALL.md):
  - flink-sql-connector-kafka-4.0.1-2.0.jar
  - flink-connector-jdbc-4.1.0-2.2.jar
  - postgresql-42.7.3.jar

Run:
    source env_flink/bin/activate
    python flink_jobs/candle_builder.py
"""

import os
import logging
from pathlib import Path

from pyflink.table import EnvironmentSettings, TableEnvironment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────
KAFKA_SERVERS   = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TIMESCALE_URL   = os.getenv(
    "TIMESCALE_JDBC_URL",
    "jdbc:postgresql://localhost:5432/tradingmaster"
)
TIMESCALE_USER  = os.getenv("TIMESCALE_USER", "user")
TIMESCALE_PASS  = os.getenv("TIMESCALE_PASS", "mysecretpassword")

# Kafka topics to consume
KAFKA_TOPICS = ",".join([
    "binance.BTCUSDT.candles",
    "binance.ETHUSDT.candles",
    "binance.BNBUSDT.candles",
    "kraken.BTCUSDT.candles",
    "kraken.ETHUSDT.candles",
    "coinbase.BTCUSD.candles",
    "coinbase.ETHUSD.candles",
])

# ── JAR paths — download these once (see INSTALL.md) ─────────────────────────
JARS_DIR = Path(__file__).parent / "jars"
JARS = [
    JARS_DIR / "flink-sql-connector-kafka-4.0.1-2.0.jar",
    JARS_DIR / "flink-connector-jdbc-core-4.0.0-2.0.jar",   # Flink 2.x: JDBC split by DB
    JARS_DIR / "postgresql-42.7.3.jar",
]


def _check_jars() -> str:
    """Verify all JARs exist and return pipeline.jars config string."""
    missing = [j for j in JARS if not j.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing JAR files in {JARS_DIR}/:\n"
            + "\n".join(f"  - {j.name}" for j in missing)
            + "\n\nRun: bash scripts/download_flink_jars.sh"
        )
    return ";".join(f"file://{j.resolve()}" for j in JARS)


def main():
    logger.info("Starting TradingMaster Flink Candle Builder...")

    # ── Setup ─────────────────────────────────────────────────────────────────
    jar_config = _check_jars()

    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)
    t_env.get_config().set("pipeline.jars", jar_config)
    t_env.get_config().set("parallelism.default", "2")

    logger.info(f"Kafka topics: {KAFKA_TOPICS}")
    logger.info(f"PostgreSQL:   {TIMESCALE_URL}")

    # ── Kafka Source Table ────────────────────────────────────────────────────
    t_env.execute_sql(f"""
        CREATE TABLE kafka_candles (
            exchange    STRING,
            ticker      STRING,
            `interval`  STRING,
            `timestamp` STRING,
            open_price  DOUBLE,
            high_price  DOUBLE,
            low_price   DOUBLE,
            close_price DOUBLE,
            volume      DOUBLE,
            proc_time   AS PROCTIME()
        ) WITH (
            'connector'                     = 'kafka',
            'topic'                         = '{KAFKA_TOPICS}',
            'properties.bootstrap.servers'  = '{KAFKA_SERVERS}',
            'properties.group.id'           = 'flink-candle-builder',
            'scan.startup.mode'             = 'latest-offset',
            'format'                        = 'json',
            'json.fail-on-missing-field'    = 'false',
            'json.ignore-parse-errors'      = 'true'
        )
    """)

    # ── PostgreSQL Sink Table ─────────────────────────────────────────────────
    t_env.execute_sql(f"""
        CREATE TABLE postgres_candles (
            exchange    STRING,
            ticker      STRING,
            `interval`  STRING,
            `timestamp` TIMESTAMP(3),
            open_price  DOUBLE,
            high_price  DOUBLE,
            low_price   DOUBLE,
            close_price DOUBLE,
            volume      DOUBLE
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = '{TIMESCALE_URL}',
            'table-name' = 'candles',
            'username'   = '{TIMESCALE_USER}',
            'password'   = '{TIMESCALE_PASS}',
            'sink.buffer-flush.max-rows'       = '100',
            'sink.buffer-flush.interval'       = '5s',
            'sink.max-retries'                 = '3'
        )
    """)

    # ── Stream: Kafka → PostgreSQL ────────────────────────────────────────────
    logger.info("Starting stream: Kafka → PostgreSQL...")
    t_env.execute_sql("""
        INSERT INTO postgres_candles
        SELECT
            exchange,
            ticker,
            `interval`,
            TO_TIMESTAMP(`timestamp`, 'yyyy-MM-dd''T''HH:mm:ss'),
            open_price,
            high_price,
            low_price,
            close_price,
            volume
        FROM kafka_candles
    """).wait()


if __name__ == "__main__":
    main()