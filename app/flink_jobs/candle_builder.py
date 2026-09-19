"""
PyFlink Candle Builder Job — Table API version

Reads unified candle JSON from Kafka topics and writes to PostgreSQL.

Resumes where it stopped: Kafka offsets are committed on every checkpoint and
the job starts from the committed offsets. The subscribed topics come from the
enabled exchanges in the database (a topic pattern + partition discovery), so
new pairs are stored without a restart. See job_config.py for details.

This version uses PyFlink Table API with SQL DDL. The required connector JARs
are added to the local TableEnvironment at startup.

Required JARs (download once, see README.md):
  - flink-sql-connector-kafka-4.0.1-2.0.jar
  - flink-connector-jdbc-core-4.0.0-2.0.jar
  - flink-connector-jdbc-postgres-4.0.0-2.0.jar
  - postgresql-42.7.3.jar

Run:
    source env_flink/bin/activate
    python flink_jobs/candle_builder.py
"""

import os
import sys
import logging
from pathlib import Path

from pyflink.table import DataTypes, EnvironmentSettings, TableEnvironment
from pyflink.table.udf import ScalarFunction, udf

try:
    from app.flink_jobs import job_config
except ImportError:
    # env_flink / the Flink image can't import the `app` package (it pulls in
    # the API's dependencies) — load job_config.py as a sibling module instead.
    sys.path.insert(0, str(Path(__file__).parent))
    import job_config

try:
    from app.logging_config import setup_json_logging
    setup_json_logging(service="tradingmaster-flink")
except ImportError:
    # app/ (and its deps) aren't guaranteed to be importable from env_flink —
    # fall back to plain logging rather than fail the job over structured logs.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
logger = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────
# env_flink doesn't load .env (see CLAUDE.md) — read directly from os.environ.
KAFKA_SERVERS   = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TIMESCALE_URL   = os.getenv(
    "TIMESCALE_JDBC_URL",
    "jdbc:postgresql://localhost:5432/tradingmaster"
)
TIMESCALE_USER  = os.getenv("TIMESCALE_USER", "user")
TIMESCALE_PASS  = os.getenv("TIMESCALE_PASS", "mysecretpassword")

# Tracing: Flink never exports OTel spans itself (the Table API's SQL execution
# has no per-record Python hook to keep an exporter alive in). Instead, when
# enabled, it extracts the W3C traceparent header CCXT→Kafka producer attaches
# and forwards the trace-id as a `trace_id` column on the persisted row, so a
# row can be correlated back to its Jaeger trace via `candles.trace_id`.
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"

# Prometheus: Flink's own JVM-side metrics reporter, independent of the
# Python `prometheus_client` registry used by the FastAPI app.
METRICS_PROM_PORT = os.getenv("FLINK_METRICS_PROMETHEUS_PORT", "9250-9260")


class ExtractTraceId(ScalarFunction):
    """
    Parses the 32-hex-char trace-id out of a W3C traceparent header value
    (format: "00-<32 hex trace-id>-<16 hex span-id>-<flags>"). Pure string
    slicing — no OTel SDK, no exporter, no network calls — this runs inside
    Flink's distributed Python UDF worker processes, where keeping a live
    OTel exporter/TracerProvider per worker would be operationally fragile.
    """

    def eval(self, traceparent):
        if traceparent is None:
            return None
        parts = traceparent.split("-")
        if len(parts) != 4 or len(parts[1]) != 32:
            return None
        return parts[1]

# ── JAR paths — download these once (see INSTALL.md) ─────────────────────────
JARS_DIR = Path(__file__).parent / "jars"
JARS = [
    JARS_DIR / "flink-sql-connector-kafka-4.0.1-2.0.jar",
    JARS_DIR / "flink-connector-jdbc-core-4.0.0-2.0.jar",   # Flink 2.x: JDBC split by DB
    JARS_DIR / "flink-connector-jdbc-postgres-4.0.0-2.0.jar",
    JARS_DIR / "postgresql-42.7.3.jar",
    JARS_DIR / "flink-metrics-prometheus-2.3.0.jar",
]


def _check_jars() -> str:
    """Verify all JARs exist and return pipeline.jars config string."""
    missing = [j for j in JARS if not j.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing JAR files in {JARS_DIR}/:\n"
            + "\n".join(f"  - {j.name}" for j in missing)
            + "\n\nDownload the missing files from Maven Central. For PostgreSQL, "
              "you need both flink-connector-jdbc-core and "
              "flink-connector-jdbc-postgres, plus the PostgreSQL JDBC driver."
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

    # Checkpointing — commits Kafka offsets so a restarted job resumes where it stopped.
    for key, value in job_config.build_runtime_config(os.environ).items():
        t_env.get_config().set(key, value)

    # Flink's own JVM-side metrics reporter — separate from prometheus_client,
    # scraped by Prometheus as its own `flink` target.
    t_env.get_config().set("metrics.reporters", "prom")
    t_env.get_config().set(
        "metrics.reporter.prom.factory.class",
        "org.apache.flink.metrics.prometheus.PrometheusReporterFactory",
    )
    t_env.get_config().set("metrics.reporter.prom.port", METRICS_PROM_PORT)

    topic_pattern = job_config.resolve_topic_pattern(TIMESCALE_URL, TIMESCALE_USER, TIMESCALE_PASS)
    discovery_interval = job_config.topic_discovery_interval(os.environ)
    logger.info(f"Kafka topic pattern: {topic_pattern} (discovery every {discovery_interval})")
    logger.info(f"PostgreSQL:   {TIMESCALE_URL}")
    logger.info(f"OTel trace-id correlation: {'enabled' if OTEL_ENABLED else 'disabled'}")

    if OTEL_ENABLED:
        t_env.create_temporary_function("extract_trace_id", udf(ExtractTraceId(), result_type=DataTypes.STRING()))

    # ── Kafka Source Table ────────────────────────────────────────────────────
    t_env.execute_sql(job_config.build_source_ddl(topic_pattern, KAFKA_SERVERS, discovery_interval))

    # ── PostgreSQL Sink Table ─────────────────────────────────────────────────
    t_env.execute_sql(job_config.build_sink_ddl(TIMESCALE_URL, TIMESCALE_USER, TIMESCALE_PASS))

    # ── Stream: Kafka → PostgreSQL ────────────────────────────────────────────
    logger.info("Starting stream: Kafka → PostgreSQL...")
    trace_id_expr = (
        "extract_trace_id(CAST(headers['traceparent'] AS STRING))" if OTEL_ENABLED else "CAST(NULL AS STRING)"
    )
    t_env.execute_sql(job_config.build_insert_sql(trace_id_expr)).wait()


if __name__ == "__main__":
    main()
