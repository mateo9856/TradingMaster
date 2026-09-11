FROM flink:2.3.0-python3.12

WORKDIR /opt/flink/jobs

# Build context is the repo root (see docker-compose.yml's `flink` service).
COPY requirements.txt .
RUN pip install --no-cache-dir apache-flink==2.3.0 python-json-logger opentelemetry-api

COPY app/flink_jobs/candle_builder.py .
COPY app/.env .

CMD ["python", "candle_builder.py"]