FROM flink:2.3.0-python3.12

WORKDIR /opt/flink/jobs

COPY requirements.txt .
RUN pip install --no-cache-dir apache-flink==2.3.0

COPY flink_jobs/candle_builder.py .
COPY .env .

CMD ["python", "candle_builder.py"]