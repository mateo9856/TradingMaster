"""
CSRF protection for cookie-authenticated requests.

A bearer token only travels when the client deliberately attaches it, so
cross-site request forgery was impossible before the cookie backend existed.
A cookie, by contrast, is attached by the browser to every request to this
origin — including one triggered by another site — so writes need a second
signal that the request really came from our own UI.

Two independent layers:

1. `SameSite=strict` on the cookie (app/auth/backend.py) — the browser does not
   attach it to any cross-site request in the first place.
2. This middleware — a cookie-carrying write must also send the
   `X-Requested-With` header. A page on another origin cannot add a custom
   header to a cross-site request without a CORS preflight, and the preflight is
   only granted to `CORS_ALLOW_ORIGINS` (app/main.py).

Requests that carry no auth cookie are left alone, so curl, the Swagger
"Authorize" button and any bearer-token integration are unaffected.
"""

import logging

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.config import AUTH_COOKIE_NAME

logger = logging.getLogger(__name__)

CSRF_HEADER = "X-Requested-With"

# Methods that don't change state. HEAD/OPTIONS included so preflights and
# health probes are never blocked.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def requires_csrf_header(request: Request) -> bool:
    """True when this request must prove it came from our own UI."""
    if request.method in SAFE_METHODS:
        return False
    return AUTH_COOKIE_NAME in request.cookies


async def csrf_protect(request: Request, call_next):
    """Blocks cookie-authenticated writes that don't carry the CSRF header."""
    if requires_csrf_header(request) and CSRF_HEADER not in request.headers:
        logger.warning(
            f"Blocked cookie-authenticated {request.method} {request.url.path} "
            f"without the {CSRF_HEADER} header"
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": (
                    f"Missing {CSRF_HEADER} header. Cookie-authenticated requests that change "
                    f"data must send it; API clients should use an Authorization: Bearer token."
                )
            },
        )
    return await call_next(request)
