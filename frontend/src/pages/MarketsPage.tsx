/**
 * Markets directory — the "dictionary": every instrument the platform tracks,
 * with what it is (name, type, category or sector, listing) and a link to its
 * live page.
 *
 * Built for people and crawlers alike: one <h1>, a captioned <table>, and real
 * <a href> links to /markets/{slug}, so search engines can discover every
 * market page from here (the sitemap lists them too).
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { Seo } from "@/components/Seo";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/field";
import { useLanguage } from "@/hooks/useLanguage";
import { api } from "@/lib/api";
import { marketName, marketSlug, marketSymbol, searchText } from "@/lib/market";
import type { AssetClass } from "@/lib/types";

type Filter = "all" | AssetClass;

export function MarketsPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const marketsQuery = useQuery({ queryKey: ["markets", language], queryFn: () => api.markets(language) });

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return (marketsQuery.data ?? [])
      .filter((m) => filter === "all" || (m.asset_class ?? "crypto") === filter)
      .filter((m) => !needle || searchText(m).includes(needle))
      .sort((a, b) =>
        (a.asset_class ?? "crypto").localeCompare(b.asset_class ?? "crypto") ||
        marketName(a).localeCompare(marketName(b), language),
      );
  }, [marketsQuery.data, query, filter, language]);

  return (
    <div className="flex flex-col gap-4">
      <Seo title={t("seo.markets_title")} description={t("seo.markets_description")} />

      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("markets.heading")}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("markets.intro")}</p>
      </header>

      <Card>
        <CardBody className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
            <Field label={t("markets.search")}>
              {(id) => (
                <Input
                  id={id}
                  type="search"
                  value={query}
                  placeholder={t("markets.searchPlaceholder")}
                  onChange={(event) => setQuery(event.target.value)}
                />
              )}
            </Field>
            <Field label={t("markets.filter")}>
              {(id) => (
                <Select id={id} value={filter} onChange={(event) => setFilter(event.target.value as Filter)}>
                  <option value="all">{t("markets.filterAll")}</option>
                  <option value="crypto">{t("common.assetGroups.crypto")}</option>
                  <option value="stock">{t("common.assetGroups.stock")}</option>
                </Select>
              )}
            </Field>
          </div>

          {marketsQuery.isPending ? (
            <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
          ) : marketsQuery.isError ? (
            <Alert tone="danger" title={t("live.apiDownTitle")}>
              {(marketsQuery.error as Error).message}
            </Alert>
          ) : visible.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("markets.noMatch", { query })}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">{t("markets.caption")}</caption>
                <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-border">
                    <th scope="col" className="py-2 pr-3 font-medium">{t("markets.name")}</th>
                    <th scope="col" className="py-2 pr-3 font-medium">{t("markets.symbol")}</th>
                    <th scope="col" className="py-2 pr-3 font-medium">{t("markets.type")}</th>
                    <th scope="col" className="py-2 pr-3 font-medium">{t("markets.classification")}</th>
                    <th scope="col" className="py-2 pr-3 font-medium">{t("markets.venue")}</th>
                    <th scope="col" className="py-2 font-medium">{t("markets.sources")}</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((market) => (
                    <tr key={market.ticker} className="border-b border-border/60 align-top">
                      <th scope="row" className="py-2 pr-3 text-left font-medium">
                        <LocalizedLink
                          to={`/markets/${marketSlug(market)}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {marketName(market)}
                        </LocalizedLink>
                        {market.description ? (
                          <p className="mt-0.5 max-w-md text-xs font-normal text-muted-foreground">
                            {market.description}
                          </p>
                        ) : null}
                      </th>
                      <td className="tabular py-2 pr-3">{marketSymbol(market)}</td>
                      <td className="py-2 pr-3">
                        <Badge tone={market.asset_class === "stock" ? "info" : "neutral"}>
                          {market.asset_class_label ?? t(`common.assetGroups.${market.asset_class ?? "crypto"}`)}
                        </Badge>
                      </td>
                      <td className="py-2 pr-3 text-muted-foreground">{market.category_label ?? "—"}</td>
                      <td className="py-2 pr-3 text-muted-foreground">{market.venue_label ?? "—"}</td>
                      <td className="py-2 text-muted-foreground">{market.exchanges.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted-foreground">{t("markets.count", { count: visible.length })}</p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
