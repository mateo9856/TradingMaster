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


class PaymentSelection(TradingInput):
    payment_method: Literal["credits", "card", "paypal"] = "credits"
    card_type: Literal["debit", "credit"] | None = None

    @model_validator(mode="after")
    def valid_payment(self):
        if (self.payment_method == "card") != (self.card_type is not None):
            raise ValueError("card_type is required only for card payments")
        return self


class PurchaseRequest(PaymentSelection):
    quote_id: UUID


class TopUpRequest(TradingInput):
    amount: CreditAmount


class FundingRequest(PaymentSelection):
    amount: CreditAmount
    payment_method: Literal["card", "paypal"]


# Strings preserve the existing wire format and the exact persisted replay
# payloads; parsing these as floats or datetimes would change that contract.
TradingNumber = Annotated[str, Field(pattern=r"^-?\d+\.\d{8}$")]


class PaymentMethodsResponse(BaseModel):
    credits: Literal["enabled", "disabled"]
    card: Literal["enabled", "disabled"]
    paypal: Literal["enabled", "disabled"]
    bank_transfer: Literal["coming_soon"]


class CapabilitiesResponse(BaseModel):
    enabled: bool
    simulated: Literal[True]
    usd_per_credit: TradingNumber
    payment_methods: PaymentMethodsResponse


class WalletResponse(BaseModel):
    balance: TradingNumber
    currency: Literal["credits"]
    usd_per_credit: TradingNumber


class QuoteResponse(BaseModel):
    id: str
    side: Literal["buy", "sell"]
    exchange: str
    ticker: str
    source_ticker: str
    quantity: TradingNumber
    amount: TradingNumber
    bid: TradingNumber
    ask: TradingNumber
    spread: TradingNumber
    spread_percent: TradingNumber
    fx_rate: TradingNumber
    source_at: str | None
    received_at: str
    expires_at: str
    delayed: bool
    trade_id: str | None


class TradeResponse(BaseModel):
    id: str
    exchange: str
    ticker: str
    source_ticker: str
    quantity: TradingNumber
    buy_price: TradingNumber
    cost: TradingNumber
    status: Literal["open", "closed"]
    opened_at: str
    closed_at: str | None
    sell_price: TradingNumber | None
    proceeds: TradingNumber | None
    realized_pnl: TradingNumber | None


class ExecutionResponse(BaseModel):
    wallet: WalletResponse
    trade: TradeResponse


class PaymentAccountResponse(BaseModel):
    available: TradingNumber
    balance: TradingNumber | None
    debt: TradingNumber | None
    credit_limit: TradingNumber | None
    transaction_limit: TradingNumber


class PaymentAccountSetResponse(BaseModel):
    debit: PaymentAccountResponse
    credit: PaymentAccountResponse
    paypal: PaymentAccountResponse


class PaymentAccountsResponse(BaseModel):
    simulated: Literal[True]
    currency: Literal["USD"]
    accounts: PaymentAccountSetResponse


class ValuationResponse(BaseModel):
    sell_value: TradingNumber
    unrealized_pnl: TradingNumber
    pnl_percent: TradingNumber
    bid: TradingNumber
    ask: TradingNumber
    spread: TradingNumber
    spread_percent: TradingNumber
    source_at: str | None
    received_at: str
    delayed: bool


class ValuedTradeResponse(TradeResponse):
    valuation: ValuationResponse | None
    valuation_error: str | None


class TradePageResponse(BaseModel):
    items: list[ValuedTradeResponse]
    total: int
    limit: int
    offset: int
