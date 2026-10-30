"""
Security response headers.

The API and the nginx front-end both served responses with no CSP, no
X-Content-Type-Options, no X-Frame-Options and no Referrer-Policy. The SPA is
served from this same origin, so these apply to the pages a browser renders as
well as to JSON responses.
"""

from app.config import AUTH_COOKIE_SECURE, DOCS_ENABLED

# The SPA is a Vite bundle with no inline scripts, so script-src can stay
# strict. 'unsafe-inline' is allowed for styles only: Tailwind and the chart
# library set element styles directly, which a strict style-src would block.
_CSP_DIRECTIVES = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    # ws:/wss: — the live candle stream connects back to this origin.
    "connect-src 'self' ws: wss:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
]

# Swagger UI and ReDoc load their assets from a CDN and evaluate inline
# scripts, so the strict policy above would leave /docs blank. Relaxed only on
# those paths, never on the app itself.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'"
)

CSP = "; ".join(_CSP_DIRECTIVES)

BASE_HEADERS = {
    # Don't let a browser second-guess a declared content type.
    "X-Content-Type-Options": "nosniff",
    # Belt and braces with frame-ancestors, for older browsers.
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


async def security_headers_middleware(request, call_next):
    response = await call_next(request)

    for header, value in BASE_HEADERS.items():
        response.headers.setdefault(header, value)

    path = request.url.path
    if DOCS_ENABLED and path.startswith(_DOCS_PATHS):
        response.headers.setdefault("Content-Security-Policy", _DOCS_CSP)
    else:
        response.headers.setdefault("Content-Security-Policy", CSP)

    # Only meaningful over HTTPS, and actively harmful on a plain-http
    # localhost (the browser would pin the host to HTTPS it can't serve).
    # AUTH_COOKIE_SECURE is the existing "this deployment is HTTPS" signal.
    if AUTH_COOKIE_SECURE:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )

    return response
