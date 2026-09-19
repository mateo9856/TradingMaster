"""
Flink job configuration — tested without PyFlink (job_config.py is pure Python).
"""

from unittest.mock import MagicMock

import pytest

from app.flink_jobs import job_config
from app.flink_jobs.job_config import (
    CATCH_ALL_TOPIC_PATTERN,
    build_insert_sql,
    build_runtime_config,
    build_sink_ddl,
    build_source_ddl,
    build_topic_pattern,
    load_enabled_exchanges,
    parse_jdbc_url,
    resolve_topic_pattern,
    topic_discovery_interval,
)

JDBC_URL = "jdbc:postgresql://postgres:5432/tradingmaster"


def fake_connect(rows=None, error=None):
    """psycopg.connect stand-in: connect(**kw) → conn (ctx mgr) → cursor (ctx mgr)."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows or []
    if error:
        cursor.execute.side_effect = error
    cursor.__enter__.return_value = cursor
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    connect = MagicMock(return_value=conn)
    connect.cursor = cursor
    return connect


# ── JDBC URL ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, expected", [
    (JDBC_URL, {"host": "postgres", "port": 5432, "dbname": "tradingmaster"}),
    ("jdbc:postgresql://localhost/tm", {"host": "localhost", "port": 5432, "dbname": "tm"}),
    ("jdbc:postgresql://db:6543/tm?sslmode=require", {"host": "db", "port": 6543, "dbname": "tm"}),
])
def test_parse_jdbc_url(url, expected):
    assert parse_jdbc_url(url) == expected


@pytest.mark.parametrize("url", ["", None, "postgresql://db/tm", "jdbc:mysql://db/tm", "jdbc:postgresql://db"])
def test_parse_jdbc_url_rejects_malformed_url(url):
    with pytest.raises(ValueError, match="Invalid PostgreSQL JDBC URL"):
        parse_jdbc_url(url)


# ── Market list from the database ────────────────────────────────────────────

def test_load_enabled_exchanges_reads_the_exchanges_table():
    connect = fake_connect(rows=[("binance",), ("kraken",)])

    assert load_enabled_exchanges(JDBC_URL, "user", "secret", connect=connect) == ["binance", "kraken"]
    connect.assert_called_once_with(host="postgres", port=5432, dbname="tradingmaster", user="user", password="secret")
    assert "WHERE enabled" in connect.cursor.execute.call_args.args[0]


def test_load_enabled_exchanges_propagates_db_errors():
    with pytest.raises(RuntimeError, match="connection refused"):
        load_enabled_exchanges(JDBC_URL, "u", "p", connect=fake_connect(error=RuntimeError("connection refused")))


def test_topic_pattern_lists_exchanges_sorted_and_escaped():
    pattern = build_topic_pattern(["kraken", "Binance", "my.exchange", "kraken"])

    assert pattern == r"^(binance|kraken|my\.exchange)\.[A-Z0-9]+\.candles$"


def test_topic_pattern_matches_unified_topics_only_for_listed_exchanges():
    import re

    pattern = re.compile(build_topic_pattern(["binance", "kraken"]))

    assert pattern.match("binance.BTCUSD.candles")
    assert pattern.match("kraken.SOLUSD.candles")
    assert not pattern.match("coinbase.BTCUSD.candles")
    assert not pattern.match("binance.BTCUSD.trades")


@pytest.mark.parametrize("exchanges", [[], ["", "  "]])
def test_topic_pattern_falls_back_to_all_candle_topics_when_empty(exchanges):
    assert build_topic_pattern(exchanges) == CATCH_ALL_TOPIC_PATTERN


def test_resolve_topic_pattern_from_db():
    connect = fake_connect(rows=[("coinbase",)])

    assert resolve_topic_pattern(JDBC_URL, "u", "p", connect=connect) == r"^(coinbase)\.[A-Z0-9]+\.candles$"


def test_resolve_topic_pattern_falls_back_on_db_error():
    connect = MagicMock(side_effect=OSError("db down"))

    assert resolve_topic_pattern(JDBC_URL, "u", "p", connect=connect) == CATCH_ALL_TOPIC_PATTERN


def test_resolve_topic_pattern_falls_back_on_bad_jdbc_url():
    assert resolve_topic_pattern("not-a-url", "u", "p", connect=fake_connect()) == CATCH_ALL_TOPIC_PATTERN


# ── Resume where it stopped ──────────────────────────────────────────────────

def test_source_resumes_from_committed_group_offsets():
    ddl = build_source_ddl("^(binance)\\..+$", "kafka:29092", "60s")

    assert "'scan.startup.mode'                       = 'group-offsets'" in ddl
    assert "'properties.auto.offset.reset'            = 'earliest'" in ddl
    assert "'properties.commit.offsets.on.checkpoint' = 'true'" in ddl
    assert f"'properties.group.id'                     = '{job_config.KAFKA_GROUP_ID}'" in ddl
    assert "latest-offset" not in ddl


def test_source_subscribes_by_pattern_with_partition_discovery():
    ddl = build_source_ddl("^(binance)\\..+$", "kafka:29092", "45s")

    assert "'topic-pattern'                           = '^(binance)\\..+$'" in ddl
    assert "'scan.topic-partition-discovery.interval' = '45s'" in ddl
    assert "'topic' " not in ddl


def test_source_reads_prices_as_strings_for_exact_decimals():
    ddl = build_source_ddl("p", "k", "60s")

    for column in ("open_price", "high_price", "low_price", "close_price", "volume", "fx_rate"):
        assert f"{column:<14}STRING" in ddl
    assert "schema_version INT" in ddl
    assert "DOUBLE" not in ddl


def test_runtime_config_enables_checkpointing_by_default():
    config = build_runtime_config({})

    assert config == {
        "execution.checkpointing.interval": "30s",
        "execution.checkpointing.mode": "AT_LEAST_ONCE",
        "restart-strategy.type": "exponential-delay",
        "table.exec.sink.require-on-conflict": "false",
        "table.exec.sink.upsert-materialize": "NONE",
    }


def test_runtime_config_env_overrides():
    config = build_runtime_config({
        "FLINK_CHECKPOINT_INTERVAL": "10 s",
        "FLINK_CHECKPOINT_DIR": "file:///checkpoints",
    })

    assert config["execution.checkpointing.interval"] == "10 s"
    assert config["execution.checkpointing.dir"] == "file:///checkpoints"


@pytest.mark.parametrize("value", ["soon", "30", "-5s", "1 week"])
def test_runtime_config_rejects_invalid_checkpoint_interval(value):
    with pytest.raises(ValueError, match="FLINK_CHECKPOINT_INTERVAL"):
        build_runtime_config({"FLINK_CHECKPOINT_INTERVAL": value})


def test_topic_discovery_interval_default_override_and_error():
    assert topic_discovery_interval({}) == "60s"
    assert topic_discovery_interval({"FLINK_TOPIC_DISCOVERY_INTERVAL": "5 min"}) == "5 min"
    with pytest.raises(ValueError, match="FLINK_TOPIC_DISCOVERY_INTERVAL"):
        topic_discovery_interval({"FLINK_TOPIC_DISCOVERY_INTERVAL": "often"})


# ── Sink + insert: intervals and unified format ──────────────────────────────

def test_sink_upserts_on_key_including_interval():
    ddl = build_sink_ddl(JDBC_URL, "user", "secret")

    assert "PRIMARY KEY (exchange, ticker, `interval`, `timestamp`) NOT ENFORCED" in ddl
    assert "'table-name' = 'candles'" in ddl


def test_sink_stores_exact_decimals_and_unified_columns():
    ddl = build_sink_ddl(JDBC_URL, "user", "secret")

    assert "close_price   DECIMAL(28, 8)" in ddl
    assert "fx_rate       DECIMAL(28, 8)" in ddl
    assert "source_ticker STRING" in ddl
    assert "quote_currency STRING" in ddl


def test_insert_only_stores_unified_messages_with_decimal_casts():
    sql = build_insert_sql("CAST(NULL AS STRING)")

    assert f"WHERE schema_version = {job_config.UNIFIED_SCHEMA_VERSION}" in sql
    assert "CAST(close_price AS DECIMAL(28, 8))" in sql
    assert "CAST(fx_rate AS DECIMAL(28, 8))" in sql
    assert sql.rstrip().splitlines()[-3].strip() == "CAST(NULL AS STRING)"


def test_insert_columns_match_sink_column_order():
    sink = build_sink_ddl(JDBC_URL, "u", "p")
    sink_columns = [
        line.split()[0].strip("`")
        for line in sink.split("(", 1)[1].split("PRIMARY KEY")[0].strip().splitlines()
    ]
    insert = build_insert_sql("trace").split("SELECT", 1)[1].split("FROM", 1)[0]
    select_items = [item.strip() for item in insert.strip().split(",\n")]

    assert len(select_items) == len(sink_columns)
    assert sink_columns[:4] == ["exchange", "ticker", "interval", "timestamp"]
    assert sink_columns[-1] == "trace_id"
