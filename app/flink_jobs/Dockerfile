FROM flink:2.3.0

# The official Flink image ships no Python at all (no "-python3.12" tag
# exists) — install it ourselves. Ubuntu 24.04 (this image's base) carries
# Python 3.12 in its default repos, which is what PyFlink 2.3.0 needs pinned.
# The image runs as the unprivileged "flink" user by default — switch to
# root for the package install, then back for everything else.
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip && \
    ln -s /usr/bin/python3.12 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/flink/jobs

# Build context is the repo root (see docker-compose.yml's `flink` service).
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages apache-flink==2.3.0 python-json-logger opentelemetry-api "psycopg[binary]"

COPY app/flink_jobs/candle_builder.py .
COPY app/flink_jobs/job_config.py .
COPY app/flink_jobs/jars ./jars
COPY app/.env .

USER flink

CMD ["python", "candle_builder.py"]