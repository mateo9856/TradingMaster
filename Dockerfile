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

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY .env .

# Front-end bundle — FastAPI serves it from /app/frontend/dist
COPY --from=frontend /build/dist ./frontend/dist

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]