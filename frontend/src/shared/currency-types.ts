/** One display currency: GET /api/v1/currencies */
export interface CurrencyInfo {
  code: string;                 // "PLN"
  name: string;                 // "Polish złoty"
  units_per_usd: string | null; // latest ECB rate, "3.91174371"
  rate_date: string | null;
}

export interface Currencies {
  default: string;              // server DEFAULT_CURRENCY
  currencies: CurrencyInfo[];
}

