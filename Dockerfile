# ── Front-end build ───────────────────────────────────────────────────────────
# The built bundle is copied into the API image, which serves it at / (see
# app/main.py). Skip this stage's output and the image is simply API-only.
FROM node:22-alpine AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ── API ───────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer). requirements.lock pins every
# package and its transitive dependencies, so the same commit always builds the
# same image — requirements.txt alone left 15 packages unconstrained.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Copy app code
COPY app/ ./app/

# Migrations ship with the image: the db-migrate Job runs `alembic upgrade head`
# from here, and the API's initContainer resolves the head revision from these
# same files (app/models/schema_check.py).
COPY alembic.ini .
COPY migrations/ ./migrations/

# Front-end bundle — FastAPI serves it from /app/frontend/dist
COPY --from=frontend /build/dist ./frontend/dist

# Run as a non-root user. `data/` is where the EOD archive writes Parquet files
# (app/jobs/eod_archive.py), so it has to be writable by that user.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

# NOTE: no `COPY .env` — configuration is injected at runtime (Compose env_file,
# Kubernetes secretRef). Baking the build host's .env into a layer would ship
# whatever credentials the builder happened to have to every registry puller,
# and the layer survives even if a later one deletes the file.

# --limit-concurrency sheds load instead of queueing without bound;
# --timeout-keep-alive reaps idle connections. Both were unset, so a client
# could hold connections open indefinitely.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--limit-concurrency", "512", \
     "--timeout-keep-alive", "15", \
     "--ws-max-size", "1048576"]
