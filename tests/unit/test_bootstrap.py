"""Application construction and deployment assets work independently of cwd."""

from importlib.resources import files
from unittest.mock import Mock

from httpx import ASGITransport, AsyncClient

from app import paths
from app.bootstrap import factory
from app.i18n import SUPPORTED_LANGUAGES, catalog
from app.models.schema_check import head_revisions


def test_application_construction_does_not_duplicate_global_instrumentation(monkeypatch, tmp_path):
    factory.configure_observability()
    instrument = Mock()
    tracing = Mock()
    monkeypatch.setattr(factory.SQLAlchemyInstrumentor, "instrument", instrument)
    monkeypatch.setattr(factory, "setup_tracing", tracing)
    first = factory.create_app(frontend_dist=tmp_path / "missing")
    second = factory.create_app(frontend_dist=tmp_path / "missing")
    assert first is not second
    assert first._is_instrumented_by_opentelemetry
    assert second._is_instrumented_by_opentelemetry
    assert len(first.user_middleware) == len(second.user_middleware)
    instrument.assert_not_called()
    tracing.assert_not_called()


async def test_explicit_frontend_directory_serves_spa_and_static_files(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("window.loaded = true;")
    (tmp_path / "index.html").write_text('<html lang="en"><head><!--app-head--></head><body>shell</body></html>')
    app = factory.create_app(frontend_dist=tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/assets/app.js")).text == "window.loaded = true;"
        page = await client.get("/pl/history")
        assert page.status_code == 200 and '<html lang="pl">' in page.text
        assert page.headers["cache-control"] == "no-cache"
        assert (await client.get("/api/v1/missing")).status_code == 404
        redirect = await client.get("/en/history?test=1")
        assert redirect.status_code == 301 and redirect.headers["location"] == "/history?test=1"
        assert (await client.get("/unknown-page")).status_code == 404


def test_deployment_paths_use_explicit_root_and_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIST", "bundle")
    assert paths.deployment_root() == tmp_path
    assert paths.deployment_path("FRONTEND_DIST", "frontend/dist") == tmp_path / "bundle"
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path / "absolute"))
    assert paths.deployment_path("FRONTEND_DIST", "frontend/dist") == tmp_path / "absolute"


def test_packaged_locales_and_migration_discovery_survive_changed_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for lang in SUPPORTED_LANGUAGES:
        assert files("app.i18n").joinpath("locales", f"{lang}.json").is_file()
        assert catalog(lang)["seo"]
    assert len(head_revisions()) == 1


async def test_lifespan_preserves_startup_and_shutdown_order(monkeypatch):
    import asyncio
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    lifecycle = importlib.import_module("app.bootstrap.lifespan")
    events = []
    session = object()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(lifecycle, "AsyncSessionLocal", lambda: context)

    def step(name):
        async def action(*args):
            events.append(name)
        return action

    for attribute in ["assert_schema_at_head", "seed_exchanges", "seed_instruments", "seed_guest"]:
        monkeypatch.setattr(lifecycle, attribute, step(attribute))

    def worker(name):
        async def run(*args):
            events.append(name + " started")
            try:
                await asyncio.Event().wait()
            finally:
                events.append(name + " stopped")
        return run

    monkeypatch.setattr(lifecycle, "watch_fiat_rates", worker("fiat"))
    monkeypatch.setattr(lifecycle, "run_producer", worker("producer"))
    monkeypatch.setattr(lifecycle, "stream_hub", SimpleNamespace(close=step("hub closed")))
    monkeypatch.setattr(lifecycle, "engine", SimpleNamespace(dispose=step("engine disposed")))
    async with lifecycle.lifespan(factory.create_app()):
        await asyncio.sleep(0)
        assert events == ["assert_schema_at_head", "seed_exchanges", "seed_instruments", "seed_guest",
                          "fiat started", "producer started"]
    assert events.index("hub closed") < events.index("producer stopped")
    assert events.index("hub closed") < events.index("fiat stopped")
    assert events[-1] == "engine disposed"
