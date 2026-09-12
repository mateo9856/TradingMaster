#!/bin/bash
# Downloads all required JAR files for the Flink candle builder job.
# Compatible with PyFlink 2.3.0
#
# NOTE: In Flink 2.x the JDBC connector is split into db-specific JARs.
# For PostgreSQL we need: flink-connector-jdbc-core + flink-connector-jdbc-postgres
#
# Usage:
#   bash scripts/download_flink_jars.sh

set -e

JARS_DIR="app/flink_jobs/jars"
mkdir -p $JARS_DIR

echo "Removing old JARs..."
rm -f $JARS_DIR/*.jar

BASE="https://repo1.maven.org/maven2/org/apache/flink"

echo "Downloading Flink 2.x connector JARs to $JARS_DIR/..."

# Kafka connector — 4.0.1-2.0 (confirmed on Maven Central)
echo "→ flink-sql-connector-kafka-4.0.1-2.0..."
curl -L -o "$JARS_DIR/flink-sql-connector-kafka-4.0.1-2.0.jar" \
  "$BASE/flink-sql-connector-kafka/4.0.1-2.0/flink-sql-connector-kafka-4.0.1-2.0.jar"

# JDBC core — required base for all JDBC connectors in Flink 2.x
echo "→ flink-connector-jdbc-core-4.0.0-2.0..."
curl -L -o "$JARS_DIR/flink-connector-jdbc-core-4.0.0-2.0.jar" \
  "$BASE/flink-connector-jdbc-core/4.0.0-2.0/flink-connector-jdbc-core-4.0.0-2.0.jar"

# JDBC PostgreSQL dialect — without this, Flink falls back to only the Derby
# factory (see CLAUDE.md's known gaps). This was previously missing from this
# script even though candle_builder.py requires it.
echo "→ flink-connector-jdbc-postgres-4.0.0-2.0..."
curl -L -o "$JARS_DIR/flink-connector-jdbc-postgres-4.0.0-2.0.jar" \
  "$BASE/flink-connector-jdbc-postgres/4.0.0-2.0/flink-connector-jdbc-postgres-4.0.0-2.0.jar"

# PostgreSQL JDBC driver
echo "→ postgresql-42.7.3..."
curl -L -o "$JARS_DIR/postgresql-42.7.3.jar" \
  "https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.3/postgresql-42.7.3.jar"

# Prometheus metrics reporter — exposes Flink's own JVM-side metrics for scraping
echo "→ flink-metrics-prometheus-2.3.0..."
curl -L -o "$JARS_DIR/flink-metrics-prometheus-2.3.0.jar" \
  "$BASE/flink-metrics-prometheus/2.3.0/flink-metrics-prometheus-2.3.0.jar"

echo ""
echo "Verifying JARs..."
ALL_OK=true
for jar in $JARS_DIR/*.jar; do
  type=$(file "$jar" | grep -o "Java archive\|HTML\|ASCII")
  size=$(ls -lh "$jar" | awk '{print $5}')
  if [[ "$type" == "Java archive" ]]; then
    echo "✓ $(basename $jar) — $size"
  else
    echo "✗ $(basename $jar) — $size — ERROR: not a valid JAR"
    head -1 "$jar"
    ALL_OK=false
  fi
done

if [ "$ALL_OK" = false ]; then
  echo "Some JARs failed to download correctly."
  exit 1
fi

echo ""
echo "All JARs downloaded successfully."