from unittest.mock import Mock

from app import config
from app.kafka.security import kafka_security_kwargs


def test_plaintext_development_transport_keeps_client_defaults(monkeypatch):
    monkeypatch.setattr(config, "KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")

    assert kafka_security_kwargs() == {}


def test_tls_transport_builds_a_default_verifying_ssl_context(monkeypatch):
    context = Mock()
    create_context = Mock(return_value=context)
    monkeypatch.setattr(config, "KAFKA_SECURITY_PROTOCOL", "SSL")
    monkeypatch.setattr(config, "KAFKA_SSL_CA_LOCATION", "/etc/ssl/custom-ca.pem")
    monkeypatch.setattr("app.kafka.security.ssl.create_default_context", create_context)

    assert kafka_security_kwargs() == {"security_protocol": "SSL", "ssl_context": context}
    create_context.assert_called_once_with(cafile="/etc/ssl/custom-ca.pem")


def test_sasl_ssl_adds_authentication_and_tls_settings(monkeypatch):
    monkeypatch.setattr(config, "KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    monkeypatch.setattr(config, "KAFKA_SASL_MECHANISM", "SCRAM-SHA-512")
    monkeypatch.setattr(config, "KAFKA_SASL_USERNAME", "tradingmaster")
    monkeypatch.setattr(config, "KAFKA_SASL_PASSWORD", "not-a-real-secret")
    monkeypatch.setattr(config, "KAFKA_SSL_CA_LOCATION", "")
    monkeypatch.setattr("app.kafka.security.ssl.create_default_context", Mock(return_value="verified-context"))

    result = kafka_security_kwargs()

    assert result == {
        "security_protocol": "SASL_SSL",
        "ssl_context": "verified-context",
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": "tradingmaster",
        "sasl_plain_password": "not-a-real-secret",
    }
