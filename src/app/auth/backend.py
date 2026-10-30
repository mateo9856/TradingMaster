"""
Two ways to carry the same JWT.

- **cookie** (`cookie_backend`) — what the browser UI uses. The token is stored
  in an http-only cookie, so page JavaScript (and anything that manages to run
  there: an XSS hole, a compromised dependency, an extension) cannot read it.
  `SameSite=strict` keeps the browser from attaching it to cross-site requests,
  which — together with the header check in csrf.py — is what replaces the CSRF
  immunity a manually-attached `Authorization` header gave us for free.
- **bearer** (`auth_backend`) — unchanged, for curl, the Swagger "Authorize"
  button and any non-browser integration.

Both use the same JWT strategy, so a token is a token whichever door it came in
by, and `current_active_user` accepts either (see users.py).
"""

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)

from app.config import (
    AUTH_COOKIE_NAME,
    AUTH_COOKIE_SECURE,
    AUTH_SECRET,
    AUTH_TOKEN_LIFETIME_SECONDS,
)

bearer_transport = BearerTransport(tokenUrl="api/v1/auth/jwt/login")

cookie_transport = CookieTransport(
    cookie_name=AUTH_COOKIE_NAME,
    cookie_max_age=AUTH_TOKEN_LIFETIME_SECONDS,
    cookie_httponly=True,      # unreadable from JavaScript
    cookie_secure=AUTH_COOKIE_SECURE,
    cookie_samesite="strict",  # never sent on a cross-site request
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=AUTH_SECRET, lifetime_seconds=AUTH_TOKEN_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

cookie_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)
