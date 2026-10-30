"""Serve the deployed frontend bundle after all API routes."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import seo
from app.paths import deployment_path

logger = logging.getLogger(__name__)
FRONTEND_DIST = deployment_path("FRONTEND_DIST", "frontend/dist")


def register_frontend(app: FastAPI, directory: Path) -> None:
    directory = directory.resolve()
    if directory.is_dir():
        app.mount("/assets", StaticFiles(directory=directory / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str, request: Request):
            """
            Serves the built single-page app: a real file when one matches, and
            index.html otherwise, so client-side routes survive a page refresh.
            index.html carries the page's own language, title and search-engine
            metadata (app/seo.py), and an unknown page is a real 404.
            """
            # An unmatched API path is a genuine 404 — never answer it with the SPA,
            # or a typo'd endpoint would look like a working page to a client.
            if full_path.startswith(("api/", "metrics", "docs", "redoc", "openapi.json")):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

            candidate = (directory / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(directory):
                return FileResponse(candidate)

            lang, path = seo.split_language(full_path)
            if lang is None:
                # /en/… — English lives at the unprefixed URL; one address per page.
                target = seo.localized_path(seo.DEFAULT_LANGUAGE, path)
                query = f"?{request.url.query}" if request.url.query else ""
                return RedirectResponse(target + query, status_code=status.HTTP_301_MOVED_PERMANENTLY)

            document, status_code = await seo.render_spa_page(request, directory / "index.html", lang, path)
            # The shell changes with every deploy; the hashed /assets it points to are what get cached.
            return HTMLResponse(document, status_code=status_code, headers={"Cache-Control": "no-cache"})

        logger.info(f"Serving front-end bundle from {directory}")
    else:
        logger.info("No front-end bundle found (frontend/dist) — API only")
