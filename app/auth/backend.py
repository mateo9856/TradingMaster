from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy

from app.config import AUTH_SECRET, AUTH_TOKEN_LIFETIME_SECONDS

bearer_transport = BearerTransport(tokenUrl="api/v1/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=AUTH_SECRET, lifetime_seconds=AUTH_TOKEN_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
