export interface TradingCapabilities {
  enabled: boolean;
  simulated: boolean;
  payment_methods: Record<string, string>;
}

export interface Wallet {
  balance: string;
  currency: "credits";
  usd_per_credit: string;
}

export type PaymentSelection = { payment_method: "credits" | "paypal"; card_type?: never }
  | { payment_method: "card"; card_type: "debit" | "credit" };

export interface PaymentAccounts {
  simulated: boolean;
  currency: "USD";
  accounts: Record<"debit" | "credit" | "paypal", {
    available: string; balance: string | null; debt: string | null;
    credit_limit: string | null; transaction_limit: string;
  }>;
}

export interface TradingQuote {
  id: string;
  side: "buy" | "sell";
  exchange: string;
  ticker: string;
  source_ticker: string;
  quantity: string;
  amount: string;
  bid: string;
  ask: string;
  spread: string;
  spread_percent: string;
  source_at: string | null;
  received_at: string;
  expires_at: string;
  delayed: boolean;
  trade_id: string | null;
}

export interface Trade {
  id: string;
  exchange: string;
  ticker: string;
  quantity: string;
  buy_price: string;
  cost: string;
  status: "open" | "closed";
  opened_at: string;
  closed_at: string | null;
  proceeds: string | null;
  realized_pnl: string | null;
  valuation_error?: string | null;
  valuation?: {
    bid: string;
    ask: string;
    spread: string;
    spread_percent: string;
    sell_value: string;
    unrealized_pnl: string;
    pnl_percent: string;
    delayed: boolean;
    source_at: string | null;
    received_at: string;
  } | null;
}

export interface TradePage {
  items: Trade[];
  total: number;
  limit: number;
  offset: number;
}

export type QuoteRequest = { side: "buy"; exchange: string; ticker: string; budget: string }
  | { side: "sell"; trade_id: string };
