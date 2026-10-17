/**
 * A page's head: title, description, canonical URL, hreflang alternates, Open
 * Graph and optional JSON-LD. React 19 hoists <title>, <meta> and <link> into
 * the document head, so a page just renders this.
 *
 * Mirrors what the server writes for the first load (app/seo.py); after that,
 * client-side navigation keeps it current. Private pages pass `noindex`.
 */

import { useLocation } from "react-router-dom";

import { useLanguage } from "@/hooks/useLanguage";
import { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, localizedPath, splitLanguage } from "@/lib/i18n";

const OG_LOCALES: Record<string, string> = {
  en: "en_US", pl: "pl_PL", de: "de_DE", fr: "fr_FR", no: "nb_NO", it: "it_IT", es: "es_ES",
};

export function Seo({
  title,
  description,
  noindex = false,
  jsonLd,
}: {
  title: string;
  description?: string;
  noindex?: boolean;
  jsonLd?: object;
}) {
  const language = useLanguage();
  const { pathname } = useLocation();
  const { path } = splitLanguage(pathname);
  const origin = window.location.origin;
  const url = origin + localizedPath(language, path);

  return (
    <>
      <title>{title}</title>
      {description ? <meta name="description" content={description} /> : null}
      {noindex ? (
        <meta name="robots" content="noindex, nofollow" />
      ) : (
        <>
          <link rel="canonical" href={url} />
          {SUPPORTED_LANGUAGES.map((code) => (
            <link key={code} rel="alternate" hrefLang={code} href={origin + localizedPath(code, path)} />
          ))}
          <link rel="alternate" hrefLang="x-default" href={origin + localizedPath(DEFAULT_LANGUAGE, path)} />
        </>
      )}
      <meta property="og:title" content={title} />
      {description ? <meta property="og:description" content={description} /> : null}
      <meta property="og:url" content={url} />
      <meta property="og:locale" content={OG_LOCALES[language]} />
      {jsonLd ? <script type="application/ld+json">{JSON.stringify(jsonLd)}</script> : null}
    </>
  );
}
