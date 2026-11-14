"""Shared Kafka TLS and SASL options for API, producer and Flink adapters."""

import ssl

from app import config


def kafka_security_kwargs() -> dict[str, object]:
    """Build the aiokafka TLS/SASL settings; PLAINTEXT remains the dev default."""
    protocol = config.KAFKA_SECURITY_PROTOCOL.upper()
    if protocol == "PLAINTEXT":
        return {}
    if protocol not in {"SSL", "SASL_SSL"}:
        raise ValueError("KAFKA_SECURITY_PROTOCOL must be PLAINTEXT, SSL or SASL_SSL")

    options: dict[str, object] = {
        "security_protocol": protocol,
        "ssl_context": ssl.create_default_context(cafile=config.KAFKA_SSL_CA_LOCATION or None),
    }
    if protocol == "SASL_SSL":
        if not config.KAFKA_SASL_USERNAME or not config.KAFKA_SASL_PASSWORD:
            raise ValueError("SASL_SSL requires KAFKA_SASL_USERNAME and KAFKA_SASL_PASSWORD")
        options.update(
            sasl_mechanism=config.KAFKA_SASL_MECHANISM,
            sasl_plain_username=config.KAFKA_SASL_USERNAME,
            sasl_plain_password=config.KAFKA_SASL_PASSWORD,
        )
    return options
