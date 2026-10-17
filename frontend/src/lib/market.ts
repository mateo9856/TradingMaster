/**
 * What the UI shows for a market when the API describes it — and a sensible
 * fallback when it doesn't (an older API, a test fixture): the symbol as the
 * name, a slug from the symbol.
 */

import type { Market } from "./types";
import { baseAsset } from "./ticker";

export function marketSymbol(market: Market): string {
  return market.symbol ?? baseAsset(market.ticker);
}

export function marketName(market: Market): string {
  return market.name ?? marketSymbol(market);
}

export function marketShortName(market: Market): string {
  return market.short_name ?? marketName(market);
}

export function marketSlug(market: Market): string {
  return market.slug ?? marketSymbol(market).toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

/** Lower-cased text a search box matches against: name, short name, symbol, ticker. */
export function searchText(market: Market): string {
  return [marketName(market), marketShortName(market), marketSymbol(market), market.ticker]
    .join(" ")
    .toLocaleLowerCase();
}
