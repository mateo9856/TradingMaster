import { Select } from "@/components/ui/field";
import { useLanguage } from "@/hooks/useLanguage";
import { useCurrency } from "@/lib/currency-context";
import { intlLocale } from "@/lib/i18n";

/** The currency's name in the UI language ("złoty polski"), or the API's English name. */
function currencyName(code: string, fallback: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "currency" }).of(code) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Picks the display currency. Every supported currency, labelled "PLN — Polish zloty" in the UI language. */
export function CurrencySelect({
  id,
  value,
  onChange,
  className,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value?: string;
  onChange?: (code: string) => void;
  className?: string;
  "aria-label"?: string;
}) {
  const { currency, currencies, setCurrency } = useCurrency();
  const locale = intlLocale(useLanguage());
  return (
    <Select
      id={id}
      aria-label={ariaLabel}
      className={className}
      value={value ?? currency}
      onChange={(event) => (onChange ?? setCurrency)(event.target.value)}
    >
      {currencies.map((option) => (
        <option key={option.code} value={option.code}>
          {option.code} — {currencyName(option.code, option.name, locale)}
        </option>
      ))}
    </Select>
  );
}
