"""Compatibility entrypoint: uvicorn app.main:app."""

from app.bootstrap.factory import create_app
from app.bootstrap.frontend import FRONTEND_DIST

__all__ = ["app", "create_app", "FRONTEND_DIST"]

app = create_app()
