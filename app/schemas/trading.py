"""Inputs for simulated trading; clients never supply executable prices."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CreditAmount = Annotated[Decimal, Field(gt=0, le=Decimal("1000000000000"),
                                       decimal_places=8, allow_inf_nan=False)]


class TradingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuoteRequest(TradingInput):
    side: Literal["buy", "sell"]
    exchange: str | None = Field(default=None, max_length=64)
    ticker: str | None = Field(default=None, max_length=40)
    budget: CreditAmount | None = None
    trade_id: UUID | None = None

    @model_validator(mode="after")
    def valid_side(self):
        if self.side == "buy":
            if not self.exchange or not self.ticker or self.budget is None or self.trade_id is not None:
                raise ValueError("Buy quotes require exchange, ticker, budget and no trade_id")
        elif self.trade_id is None or any(v is not None for v in (self.exchange, self.ticker, self.budget)):
            raise ValueError("Sell quotes require only trade_id")
        return self


class ExecuteRequest(TradingInput):
    quote_id: UUID


class TopUpRequest(TradingInput):
    amount: CreditAmount
