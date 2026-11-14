import pytest

from app.config import ConfigError, validate_transport_security


def secure_values(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://user:secret@db/tradingmaster?sslmode=require",
        "kafka_security_protocol": "SASL_SSL",
        "rate_limit_enabled": True,
        "rate_limit_backend": "redis",
        "rate_limit_redis_url": "rediss://redis.example:6379/0",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"database_url": "postgresql+asyncpg://user:secret@db/tradingmaster"}, "database TLS"),
        ({"database_url": "postgresql+asyncpg://user:secret@db/tradingmaster?ssl=require"}, "database TLS"),
        ({"database_url": "postgresql+asyncpg://user:secret@db/tradingmaster?sslmode=true"}, "database TLS"),
        ({"database_url": "postgresql+asyncpg://user:secret@db/tradingmaster?sslmode=require&sslmode=disable"}, "database TLS"),
        ({"kafka_security_protocol": "PLAINTEXT"}, "Kafka TLS"),
        ({"rate_limit_backend": "memory"}, "shared rate-limit"),
        ({"rate_limit_redis_url": "redis://redis.example:6379/0"}, "Redis TLS"),
        ({"rate_limit_enabled": False}, "rate limiting"),
    ],
)
def test_production_transport_validation_rejects_unencrypted_or_local_modes(overrides, message):
    with pytest.raises(ConfigError, match=message):
        validate_transport_security(**secure_values(**overrides))


def test_production_transport_validation_accepts_tls_and_shared_limits():
    validate_transport_security(**secure_values())
