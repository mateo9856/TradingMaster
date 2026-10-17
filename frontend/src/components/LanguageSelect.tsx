import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Select } from "@/components/ui/field";
import { useLanguage } from "@/hooks/useLanguage";
import {
  SUPPORTED_LANGUAGES,
  isLanguage,
  languageAutonym,
  localizedPath,
  splitLanguage,
  storeLanguage,
} from "@/lib/i18n";

/**
 * Switches the UI language and stays on the same page: /pl/markets/x → /de/markets/x.
 * Each language is listed in its own name ("Polski", "Deutsch") — the reader of
 * that option is someone who speaks it. The choice is remembered.
 */
export function LanguageSelect({ className }: { className?: string }) {
  const { t } = useTranslation();
  const language = useLanguage();
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <Select
      aria-label={t("nav.language")}
      className={className}
      value={language}
      onChange={(event) => {
        const next = event.target.value;
        if (!isLanguage(next)) return;
        storeLanguage(next);
        const { path } = splitLanguage(location.pathname);
        navigate(localizedPath(next, path) + location.search);
      }}
    >
      {SUPPORTED_LANGUAGES.map((code) => (
        <option key={code} value={code} lang={code}>
          {languageAutonym(code)}
        </option>
      ))}
    </Select>
  );
}
