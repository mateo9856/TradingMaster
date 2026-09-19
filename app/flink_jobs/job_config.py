"""
Pure-Python configuration builders for the Flink candle builder job.

Kept free of any pyflink import so it can be unit-tested from the API venv
(`env/`) — candle_builder.py only wires these strings into a TableEnvironment.

Resume-where-it-stopped design:
  - the Kafka source starts from the consumer group's committed offsets
    ('scan.startup.mode' = 'group-offsets'), falling back to the earliest
    retained offset for a group/topic that has never committed;
  - checkpointing is enabled, and the Kafka source commits its offsets back
    to the group on every completed checkpoint;
  - the JDBC sink flushes on every checkpoint and upserts on
    (exchange, ticker, interval, timestamp), so re-reading a message after a
    restart (at-least-once) just rewrites the same row.
  => a job that was down for 10 minutes catches up those 10 minutes on start,
     as long as Kafka still retains them (7 days by default).

Market list: the enabled exchanges are loaded from the `exchanges` table and
turned into a topic *pattern* (not a fixed topic list), combined with
periodic partition discovery — so a pair added through the API is picked up
and saved without restarting the job. A new exchange needs a restart.
"""

import logging
import re
from typing import Callable, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

# Must match the "schema_version" the producer writes (app/kafka/producer.py).
# Older messages (float prices, native tickers) are skipped on replay.
UNIFIED_SCHEMA_VERSION: int = 2

# Used when the exchange list can't be loaded (or is empty): subscribe to every
# candle topic rather than silently storing nothing.
CATCH_ALL_TOPIC_PATTERN: str = r"^[a-z0-9_-]+\.[A-Z0-9]+\.candles$"

KAFKA_GROUP_ID: str = "flink-candle-builder"
DECIMAL_TYPE: str = "DECIMAL(28, 8)"

DEFAULT_CHECKPOINT_INTERVAL: str = "30s"
DEFAULT_TOPIC_DISCOVERY_INTERVAL: str = "60s"

_JDBC_URL = re.compile(
    r"^jdbc:postgresql://(?P<host>[^:/?#]+)(?::(?P<port>\d+))?/(?P<dbname>[^/?#]+)(?:\?.*)?$"
)
_DURATION = re.compile(r"^\d+\s*(ms|s|min|m|h|d)$")

_PRICE_COLUMNS = ("open_price", "high_price", "low_price", "close_price", "volume")


# ── Database: enabled exchanges ──────────────────────────────────────────────

def parse_jdbc_url(url: str) -> dict:
    """Splits jdbc:postgresql://host[:port]/db into psycopg connection kwargs."""
    match = _JDBC_URL.match(url or "")
    if not match:
        raise ValueError(f"Invalid PostgreSQL JDBC URL: {url!r}")
    return {
        "host": match["host"],
        "port": int(match["port"] or 5432),
        "dbname": match["dbname"],
    }


def load_enabled_exchanges(
    jdbc_url: str,
    user: str,
    password: str,
    connect: Optional[Callable] = None,
) -> list[str]:
    """Names of the enabled exchanges, read from the `exchanges` table."""
    if connect is None:
        import psycopg  # only needed inside the Flink image / env_flink
        connect = psycopg.connect

    params = parse_jdbc_url(jdbc_url)
    with connect(**params, user=user, password=password) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM exchanges WHERE enabled ORDER BY name")
            return [row[0] for row in cur.fetchall()]


def build_topic_pattern(exchanges: Iterable[str]) -> str:
    """Kafka topic regex for the given exchanges, e.g. ^(binance|kraken)\\.[A-Z0-9]+\\.candles$."""
    names = sorted({name.strip().lower() for name in exchanges if name and name.strip()})
    if not names:
        logger.warning("No enabled exchanges — subscribing to all candle topics")
        return CATCH_ALL_TOPIC_PATTERN
    alternatives = "|".join(re.escape(name) for name in names)
    return rf"^({alternatives})\.[A-Z0-9]+\.candles$"


def resolve_topic_pattern(
    jdbc_url: str,
    user: str,
    password: str,
    connect: Optional[Callable] = None,
) -> str:
    """Topic pattern from the DB; falls back to the catch-all pattern on any DB error."""
    try:
        exchanges = load_enabled_exchanges(jdbc_url, user, password, connect=connect)
    except Exception as e:
        logger.warning(f"Could not load exchanges from DB ({e}) — subscribing to all candle topics")
        return CATCH_ALL_TOPIC_PATTERN
    logger.info(f"Enabled exchanges from DB: {exchanges}")
    return build_topic_pattern(exchanges)


# ── Runtime configuration ────────────────────────────────────────────────────

def _duration(env: Mapping[str, str], key: str, default: str) -> str:
    value = (env.get(key) or default).strip()
    if not _DURATION.match(value):
        raise ValueError(f"{key} must be a duration like '30s' or '1 min', got {value!r}")
    return value


def build_runtime_config(env: Mapping[str, str]) -> dict[str, str]:
    """Flink configuration that makes the job checkpoint (and so commit offsets) and self-heal."""
    config = {
        "execution.checkpointing.interval": _duration(env, "FLINK_CHECKPOINT_INTERVAL", DEFAULT_CHECKPOINT_INTERVAL),
        # The upsert sink makes replays idempotent — exactly-once isn't needed.
        "execution.checkpointing.mode": "AT_LEAST_ONCE",
        # Transient DB/Kafka outages restart the job instead of killing it.
        "restart-strategy.type": "exponential-delay",
        # Flink 2.3+ refuses an insert-only query into a sink with a primary key
        # unless the SQL has an ON CONFLICT clause. Conflicts are already resolved
        # by PostgreSQL (the JDBC sink's ON CONFLICT ... DO UPDATE, last write
        # wins), and every key comes from one single-partition topic, so per-key
        # order is preserved — Flink's state-heavy DO DEDUPLICATE isn't needed.
        "table.exec.sink.require-on-conflict": "false",
        # The source is insert-only (no retractions), so Flink's upsert
        # materializer — which keeps every key's history in state — adds nothing
        # but ever-growing checkpoints.
        "table.exec.sink.upsert-materialize": "NONE",
    }
    checkpoint_dir = (env.get("FLINK_CHECKPOINT_DIR") or "").strip()
    if checkpoint_dir:
        config["execution.checkpointing.dir"] = checkpoint_dir
    return config


def topic_discovery_interval(env: Mapping[str, str]) -> str:
    return _duration(env, "FLINK_TOPIC_DISCOVERY_INTERVAL", DEFAULT_TOPIC_DISCOVERY_INTERVAL)


# ── SQL ──────────────────────────────────────────────────────────────────────

def build_source_ddl(topic_pattern: str, bootstrap_servers: str, discovery_interval: str) -> str:
    """
    Kafka source table. Prices arrive as fixed-point strings and are read as
    STRING (not DOUBLE) so they're cast straight to DECIMAL without rounding.
    `headers` is a Kafka connector metadata column — lets SQL read the
    traceparent header the producer attaches, with no DataStream API needed.
    """
    price_columns = ",\n            ".join(f"{col:<14}STRING" for col in _PRICE_COLUMNS)
    return f"""
        CREATE TABLE kafka_candles (
            schema_version INT,
            exchange      STRING,
            ticker        STRING,
            source_ticker STRING,
            quote_currency STRING,
            fx_rate       STRING,
            `interval`    STRING,
            `timestamp`   STRING,
            {price_columns},
            headers       MAP<STRING, BYTES> METADATA VIRTUAL,
            proc_time     AS PROCTIME()
        ) WITH (
            'connector'                               = 'kafka',
            'topic-pattern'                           = '{topic_pattern}',
            'scan.topic-partition-discovery.interval' = '{discovery_interval}',
            'properties.bootstrap.servers'            = '{bootstrap_servers}',
            'properties.group.id'                     = '{KAFKA_GROUP_ID}',
            'scan.startup.mode'                       = 'group-offsets',
            'properties.auto.offset.reset'            = 'earliest',
            'properties.commit.offsets.on.checkpoint' = 'true',
            'format'                                  = 'json',
            'json.fail-on-missing-field'              = 'false',
            'json.ignore-parse-errors'                = 'true'
        )
    """


def build_sink_ddl(jdbc_url: str, user: str, password: str) -> str:
    """JDBC sink — the declared primary key makes the connector emit ON CONFLICT ... DO UPDATE."""
    price_columns = ",\n            ".join(f"{col:<14}{DECIMAL_TYPE}" for col in _PRICE_COLUMNS)
    return f"""
        CREATE TABLE postgres_candles (
            exchange      STRING,
            ticker        STRING,
            `interval`    STRING,
            `timestamp`   TIMESTAMP(3),
            {price_columns},
            source_ticker STRING,
            quote_currency STRING,
            fx_rate       {DECIMAL_TYPE},
            trace_id      STRING,
            PRIMARY KEY (exchange, ticker, `interval`, `timestamp`) NOT ENFORCED
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = '{jdbc_url}',
            'table-name' = 'candles',
            'username'   = '{user}',
            'password'   = '{password}',
            'sink.buffer-flush.max-rows'       = '100',
            'sink.buffer-flush.interval'       = '5s',
            'sink.max-retries'                 = '3'
        )
    """


def build_insert_sql(trace_id_expr: str) -> str:
    """Kafka → PostgreSQL stream; drops messages that aren't in the unified format."""
    price_casts = ",\n            ".join(f"CAST({col} AS {DECIMAL_TYPE})" for col in _PRICE_COLUMNS)
    return f"""
        INSERT INTO postgres_candles
        SELECT
            exchange,
            ticker,
            `interval`,
            TO_TIMESTAMP(`timestamp`, 'yyyy-MM-dd''T''HH:mm:ss'),
            {price_casts},
            source_ticker,
            quote_currency,
            CAST(fx_rate AS {DECIMAL_TYPE}),
            {trace_id_expr}
        FROM kafka_candles
        WHERE schema_version = {UNIFIED_SCHEMA_VERSION}
    """
