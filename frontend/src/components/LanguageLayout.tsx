/**
 * The `/:lang?` route: validates the language prefix, loads that language's
 * text and switches the UI to it, and — on a first visit to an unprefixed
 * (English) URL — sends the visitor to their own language.
 *
 * The redirect only happens for a visitor who has never chosen a language;
 * picking one in the header (English included) is remembered and wins. It
 * runs in the browser, never on the server: crawlers have no location and
 * must be able to reach every language's URL as it is.
 */

import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router-dom";

import { NotFoundPage } from "@/pages/NotFoundPage";
import {
  DEFAULT_LANGUAGE,
  activateLanguage,
  detectLanguage,
  isLanguage,
  localizedPath,
  readStoredLanguage,
  type Language,
} from "@/lib/i18n";
import { browserEnvironment } from "@/lib/currency";

export function LanguageLayout() {
  const { lang } = useParams();
  const location = useLocation();
  const [loaded, setLoaded] = useState<Language | null>(null);

  const valid = lang === undefined || isLanguage(lang);
  const language: Language = lang !== undefined && isLanguage(lang) ? lang : DEFAULT_LANGUAGE;

  useEffect(() => {
    if (!valid) return;
    let cancelled = false;
    activateLanguage(language)
      .catch((error) => console.warn(`Could not load the ${language} translation:`, error))
      .finally(() => {
        if (cancelled) return;
        document.documentElement.lang = language;
        setLoaded(language);
      });
    return () => {
      cancelled = true;
    };
  }, [language, valid]);

  if (!valid) return <NotFoundPage />;

  const rest = lang === undefined ? location.pathname : location.pathname.slice(lang.length + 1) || "/";

  // /en/… — English lives at the unprefixed URL.
  if (lang === DEFAULT_LANGUAGE) {
    return <Navigate to={rest + location.search} replace />;
  }

  if (lang === undefined && readStoredLanguage() === null) {
    const { timeZone, languages } = browserEnvironment();
    const detected = detectLanguage({ languages, timeZone });
    if (detected !== DEFAULT_LANGUAGE) {
      return <Navigate to={localizedPath(detected, location.pathname) + location.search} replace />;
    }
  }

  // Don't flash English text while another language's catalogue loads.
  if (loaded !== language) return null;
  return <Outlet />;
}
