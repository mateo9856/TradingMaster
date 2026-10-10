import { Select } from "@/components/ui/field";
import { useCurrency } from "@/lib/currency-context";

/** Picks the display currency. Every supported currency, labelled "PLN — Polish złoty". */
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
          {option.code} — {option.name}
        </option>
      ))}
    </Select>
  );
}
