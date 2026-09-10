from pydantic import BaseModel, Field


class ExchangeCreate(BaseModel):
    name: str = Field(..., examples=["binance"])
    method: str = Field(..., examples=["multi", "ohlcv", "trades"])


class ExchangeResponse(BaseModel):
    id: int
    name: str
    method: str
    enabled: bool

    class Config:
        from_attributes = True


class SymbolCreate(BaseModel):
    ticker: str = Field(..., examples=["BTC/USDT"])
    interval: str = Field("1m", examples=["1m", "5m", "1h"])


class SymbolResponse(BaseModel):
    id: int
    exchange_id: int
    ticker: str
    interval: str
    enabled: bool

    class Config:
        from_attributes = True
