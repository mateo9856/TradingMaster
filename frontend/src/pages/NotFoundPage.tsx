import { useTranslation } from "react-i18next";

import { LocalizedLink } from "@/components/LocalizedLink";
import { Seo } from "@/components/Seo";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2 text-sm">
      <Seo title={t("seo.not_found_title")} noindex />
      <h1 className="text-lg font-semibold">{t("common.notFound")}</h1>
      <LocalizedLink to="/markets" className="text-muted-foreground underline underline-offset-4 hover:text-foreground">
        {t("common.allMarkets")}
      </LocalizedLink>
    </section>
  );
}
