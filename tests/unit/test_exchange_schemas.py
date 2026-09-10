from datetime import date, datetime

from app.schemas import CandleHistoryResponse, ExchangeCreate, SymbolCreate


def test_exchange_and_symbol_schema_defaults():
    assert ExchangeCreate(name="binance", method="multi").name == "binance"
    assert SymbolCreate(ticker="BTC/USDT").interval == "1m"


def test_history_response_validates_orm_shaped_data():
    response = CandleHistoryResponse.model_validate({
        "id": 1,
        "exchange": "binance",
        "ticker": "BTC/USDT",
        "interval": "1m",
        "trade_date": date(2026, 6, 23),
        "timestamp": datetime(2026, 6, 23, 12, 0),
        "open_price": 1.0,
        "high_price": 2.0,
        "low_price": 0.5,
        "close_price": 1.5,
        "volume": 10.0,
        "archived_at": datetime(2026, 6, 24, 0, 0),
    })

    assert response.trade_date == date(2026, 6, 23)
