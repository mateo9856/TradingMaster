from decimal import Decimal
import os
import runpy
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from app import config
from app.trading.payments import authorize


@pytest.mark.parametrize('kind,balance,amount,expected', [
    ('debit', '100', '100', '0'), ('paypal', '100', '100', '0'),
    ('credit', '900', '100', '1000'), ('debit', '100', '40', '60'),
    ('paypal', '100', '40', '60'), ('credit', '0', '40', '40'),
])
def test_authorization(kind, balance, amount, expected, monkeypatch):
    monkeypatch.setattr(config, 'SIMULATED_CREDIT_LIMIT', Decimal('1000'))
    monkeypatch.setattr(config, f'SIMULATED_{kind.upper()}_TRANSACTION_LIMIT', Decimal('100'))
    assert authorize(kind, Decimal(balance), Decimal(amount)) == Decimal(expected)


@pytest.mark.parametrize('kind,balance,amount,error', [
    ('debit', '10', '100', 'payment funds'), ('paypal', '10', '100', 'payment funds'),
    ('credit', '950', '100', 'available credit'),
    ('debit', '10000', '101', 'transaction limit'), ('credit', '0', '101', 'transaction limit'),
    ('paypal', '10000', '101', 'transaction limit'),
])
def test_declines(kind, balance, amount, error, monkeypatch):
    monkeypatch.setattr(config, 'SIMULATED_CREDIT_LIMIT', Decimal('1000'))
    monkeypatch.setattr(config, f'SIMULATED_{kind.upper()}_TRANSACTION_LIMIT', Decimal('100'))
    with pytest.raises(HTTPException, match=error):
        authorize(kind, Decimal(balance), Decimal(amount))


@pytest.mark.parametrize('name', list(config._PAYMENT_DEFAULTS))
@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '1e20', '0.000000001'])
def test_invalid_payment_configuration(name, value, monkeypatch):
    monkeypatch.setattr(config, name, Decimal(value))
    with pytest.raises(config.ConfigError, match=name):
        config.validate_config()


def test_initial_debt_cannot_exceed_credit_limit(monkeypatch):
    monkeypatch.setattr(config, 'SIMULATED_CREDIT_LIMIT', Decimal('10'))
    monkeypatch.setattr(config, 'SIMULATED_CREDIT_INITIAL_DEBT', Decimal('11'))
    with pytest.raises(config.ConfigError, match='exceeds'):
        config.validate_config()


@pytest.mark.parametrize('override,expected', [(None, '7500'), ('1234.50', '1234.50')])
def test_initial_credit_environment_fallback(override, expected):
    values = {'DEV_INITIAL_CREDITS': '7500'}
    if override is not None:
        values['TRADING_INITIAL_CREDITS'] = override
    with patch.dict(os.environ, values, clear=True), patch('dotenv.load_dotenv'):
        settings = runpy.run_path(str(config.REPO_ROOT / 'app/config.py'))
    assert settings['TRADING_INITIAL_CREDITS'] == Decimal(expected)
    assert settings['SIMULATED_TRADING_ENABLED'] is False
    assert settings['SIMULATED_DEBIT_BALANCE'] == Decimal('10000')
    assert settings['SIMULATED_PAYPAL_TRANSACTION_LIMIT'] == Decimal('1000')


def test_non_numeric_configuration_is_rejected():
    with patch.dict(os.environ, {'SIMULATED_DEBIT_BALANCE': 'invalid'}, clear=True), patch('dotenv.load_dotenv'):
        with pytest.raises(ValueError, match='SIMULATED_DEBIT_BALANCE'):
            runpy.run_path(str(config.REPO_ROOT / 'app/config.py'))


def test_production_enablement_retains_security_validation(monkeypatch):
    monkeypatch.setattr(config, 'APP_ENV', 'production')
    monkeypatch.setattr(config, 'IS_PRODUCTION', True)
    monkeypatch.setattr(config, 'DEV_TRADING_ENABLED', False)
    monkeypatch.setattr(config, 'DEV_GUEST_ENABLED', False)
    monkeypatch.setattr(config, 'SIMULATED_TRADING_ENABLED', True)
    monkeypatch.setattr(config, 'AUTH_SECRET', 'a' * 48)
    monkeypatch.setattr(config, 'AUTH_COOKIE_SECURE', True)
    monkeypatch.setattr(config, 'CORS_ALLOW_ORIGINS', ['https://example.com'])
    config.validate_config()
    monkeypatch.setattr(config, 'AUTH_COOKIE_SECURE', False)
    with pytest.raises(config.ConfigError, match='AUTH_COOKIE_SECURE'):
        config.validate_config()
    monkeypatch.setattr(config, 'DEV_GUEST_ENABLED', True)
    with pytest.raises(config.ConfigError, match='APP_ENV=development'):
        config.validate_config()
