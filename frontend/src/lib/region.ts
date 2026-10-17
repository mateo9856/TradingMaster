/**
 * Where the browser is: time zone and language tag → ISO 3166 region. Used to
 * pick both the display currency (./currency) and the UI language (./i18n).
 */

/** IANA time zone → region. Zones not listed (e.g. Asia/Dubai) fall through to the language. */
export const TIMEZONE_REGION: Record<string, string> = {
  "Europe/Warsaw": "PL", "Europe/Oslo": "NO", "Arctic/Longyearbyen": "NO", "Europe/Stockholm": "SE",
  "Europe/Copenhagen": "DK", "Atlantic/Reykjavik": "IS", "Europe/Prague": "CZ", "Europe/Budapest": "HU",
  "Europe/Bucharest": "RO", "Europe/Zurich": "CH", "Europe/Vaduz": "LI", "Europe/London": "GB",
  "Europe/Istanbul": "TR",
  "Europe/Berlin": "DE", "Europe/Paris": "FR", "Europe/Madrid": "ES", "Europe/Rome": "IT",
  "Europe/Amsterdam": "NL", "Europe/Brussels": "BE", "Europe/Vienna": "AT", "Europe/Dublin": "IE",
  "Europe/Lisbon": "PT", "Europe/Helsinki": "FI", "Europe/Athens": "GR", "Europe/Tallinn": "EE",
  "Europe/Riga": "LV", "Europe/Vilnius": "LT", "Europe/Bratislava": "SK", "Europe/Ljubljana": "SI",
  "Europe/Luxembourg": "LU", "Europe/Malta": "MT", "Europe/Zagreb": "HR", "Europe/Sofia": "BG",
  "Asia/Nicosia": "CY", "Europe/Monaco": "MC",
  "Asia/Tokyo": "JP", "Asia/Shanghai": "CN", "Asia/Hong_Kong": "HK", "Asia/Seoul": "KR",
  "Asia/Singapore": "SG", "Asia/Kolkata": "IN", "Asia/Calcutta": "IN", "Asia/Jakarta": "ID",
  "Asia/Kuala_Lumpur": "MY", "Asia/Manila": "PH", "Asia/Bangkok": "TH", "Asia/Jerusalem": "IL",
  "Asia/Tel_Aviv": "IL", "Africa/Johannesburg": "ZA", "Pacific/Auckland": "NZ",
  "America/Mexico_City": "MX", "America/Sao_Paulo": "BR",
  "America/Toronto": "CA", "America/Vancouver": "CA", "America/Edmonton": "CA",
  "America/Winnipeg": "CA", "America/Halifax": "CA", "America/St_Johns": "CA", "America/Regina": "CA",
  "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US", "America/Phoenix": "US",
  "America/Los_Angeles": "US", "America/Anchorage": "US", "Pacific/Honolulu": "US",
};

/** The region a time zone belongs to, including every Australia/* zone. */
export function regionForTimeZone(timeZone: string | undefined): string | null {
  if (!timeZone) return null;
  if (timeZone.startsWith("Australia/")) return "AU";
  return TIMEZONE_REGION[timeZone] ?? null;
}

/** The region of a BCP 47 tag: "pl-PL" → "PL", and a bare "pl" → "PL" via likely subtags. */
export function regionForLanguage(tag: string): string | null {
  try {
    const locale = new Intl.Locale(tag);
    return (locale.region ?? locale.maximize().region ?? null)?.toUpperCase() ?? null;
  } catch {
    return null;
  }
}
