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

# Where the API lives. The default matches Compose, where the API is the `api`
# service on the same network. Overridden per environment:
#   docker-compose.yml  -> api:8000            (or FRONTEND_API_HOST)
#   k8s/base/frontend.yaml -> fastapi-service:8000
#   API on your host    -> host.docker.internal:8000
ENV API_HOST=api:8000
# nginx's own template processing substitutes API_HOST at startup.
ENV NGINX_ENVSUBST_TEMPLATE_SUFFIX=.template

# Run unprivileged. nginx:alpine ships an `nginx` user and writes its pid,
# cache and temp files under /var/cache/nginx and /var/run, so those need to be
# writable by it; port 8080 is already above 1024, so no capability is needed
# to bind it.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/cache/nginx /var/run/nginx.pid /usr/share/nginx/html /etc/nginx/conf.d
USER nginx

EXPOSE 8080
