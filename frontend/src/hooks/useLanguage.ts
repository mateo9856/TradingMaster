import { useTranslation } from "react-i18next";

import { DEFAULT_LANGUAGE, isLanguage, type Language } from "@/lib/i18n";

/** The active UI language; re-renders the caller when it changes. */
export function useLanguage(): Language {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  return isLanguage(language) ? language : DEFAULT_LANGUAGE;
}
