"""
The API serves the built front-end bundle (frontend/dist) when it exists, and
stays API-only when it doesn't — so `pytest`, `uvicorn --reload` and the Vite
dev server all work without a build.
"""

import app.main as main_module


def test_frontend_dist_path_points_at_the_frontend_build():
    assert main_module.FRONTEND_DIST.name == "dist"
    assert main_module.FRONTEND_DIST.parent.name == "frontend"


def test_spa_catch_all_is_registered_last():
    """Starlette matches routes in registration order — the catch-all must be last."""
    paths = [getattr(route, "path", "") for route in main_module.app.routes]
    catch_all = [i for i, path in enumerate(paths) if path == "/{full_path:path}"]

    assert paths.index("/health") < len(paths)
    assert paths.count("/{full_path:path}") <= 1
    if catch_all:
        assert catch_all[0] == len(paths) - 1
        assert paths.index("/metrics") < catch_all[0]
        assert paths.index("/health") < catch_all[0]


async def test_unknown_api_path_still_returns_404_not_the_spa(client):
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404


async def test_health_is_not_shadowed_by_the_frontend(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_bundle_is_served_only_when_it_has_been_built():
    """
    No build (a fresh clone, or `pytest` in CI) → API only, no mount and no
    catch-all. After `npm run build` both appear. Either state is valid; they
    must agree with whether frontend/dist actually exists.
    """
    paths = [getattr(route, "path", "") for route in main_module.app.routes]
    built = main_module.FRONTEND_DIST.is_dir()

    assert ("/assets" in paths) is built
    assert ("/{full_path:path}" in paths) is built


async def test_spa_routes_fall_back_to_index_html(client):
    """A deep link like /history must return the app, not a 404 — but only once built."""
    response = await client.get("/history")

    if main_module.FRONTEND_DIST.is_dir():
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    else:
        assert response.status_code == 404


async def test_metrics_is_served_on_the_exact_path_prometheus_scrapes(client):
    """
    Prometheus scrapes /metrics with no trailing slash (see
    observability/prometheus/prometheus.yml), and the System screen fetches the
    same path — the SPA catch-all must not swallow it.
    """
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert (await client.get("/metrics/")).status_code == 200
