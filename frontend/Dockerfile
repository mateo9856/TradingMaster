# Standalone front-end container: nginx serving the built SPA and proxying the
# API. Used by the `frontend` service in docker-compose.yml and by
# k8s/base/frontend.yaml. The alternative — letting FastAPI serve the bundle —
# needs no container of its own (see the root Dockerfile).

FROM node:22-alpine AS build
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /build/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template

# Where the API lives, e.g. "host.docker.internal:8000" (Compose, API on the
# host) or "fastapi-service:8000" (Kubernetes).
ENV API_HOST=host.docker.internal:8000
# nginx's own template processing substitutes API_HOST at startup.
ENV NGINX_ENVSUBST_TEMPLATE_SUFFIX=.template

EXPOSE 8080
