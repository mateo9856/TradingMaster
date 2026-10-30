import { ApiError, requestData, query } from "@/shared/http";
import type { PaymentAccounts, PaymentSelection, QuoteRequest, Trade, TradePage, TradingCapabilities, TradingQuote, Wallet } from "./types";

export const tradingApi = {
  tradingCapabilities(): Promise<TradingCapabilities> {
    return requestData("/api/v1/trading/capabilities");
  },
  initializeWallet(): Promise<Wallet> {
    return requestData("/api/v1/trading/wallet/initialize", { method: "POST" });
  },
  async tradingWallet(): Promise<Wallet> {
    try { return await requestData<Wallet>("/api/v1/trading/wallet"); }
    catch (error) {
      if (error instanceof ApiError && error.isNotFound) return tradingApi.initializeWallet();
      throw error;
    }
  },
  paymentAccounts(): Promise<PaymentAccounts> {
    return requestData("/api/v1/trading/payment-accounts");
  },
  fundWallet(amount: string, key: string, payment: PaymentSelection): Promise<Wallet> {
    return requestData("/api/v1/trading/wallet/top-ups", {
      method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({ amount, ...payment }),
    });
  },
  tradingQuote(body: QuoteRequest): Promise<TradingQuote> {
    return requestData("/api/v1/trading/quotes", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  },
  buyTrade(quoteId: string, key: string, payment: PaymentSelection = { payment_method: "credits" }): Promise<{ wallet: Wallet; trade: Trade }> {
    return requestData("/api/v1/trading/trades", {
      method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({ quote_id: quoteId, ...payment }),
    });
  },
  sellTrade(tradeId: string, quoteId: string, key: string): Promise<{ wallet: Wallet; trade: Trade }> {
    return requestData(`/api/v1/trading/trades/${tradeId}/sell`, {
      method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({ quote_id: quoteId }),
    });
  },
  trades(status: "open" | "closed", offset = 0): Promise<TradePage> {
    return requestData(`/api/v1/trading/trades${query({ status, offset })}`);
  },
  demoTopUp(amount: string, key: string): Promise<Wallet> {
    return requestData("/api/v1/trading/wallet/demo-top-ups", {
      method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({ amount }),
    });
  },
};
