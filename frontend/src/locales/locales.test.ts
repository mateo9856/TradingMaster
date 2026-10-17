/**
 * Translation completeness. A missing key would silently show English (or the
 * key itself) to a Polish reader; a lost {{placeholder}} would drop a number
 * from a sentence. Both fail here instead.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { SUPPORTED_LANGUAGES, intlLocale } from "@/lib/i18n";
import de from "./de.json";
import en from "./en.json";
import es from "./es.json";
import fr from "./fr.json";
import it_ from "./it.json";
import no from "./no.json";
import pl from "./pl.json";

const CATALOGUES: Record<string, Record<string, unknown>> = { en, pl, de, fr, no, it: it_, es };
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

function flatten(node: unknown, prefix = ""): Record<string, string> {
  if (typeof node === "string") return { [prefix]: node };
  return Object.entries(node as Record<string, unknown>).reduce(
    (all, [key, value]) => ({ ...all, ...flatten(value, prefix ? `${prefix}.${key}` : key) }),
    {} as Record<string, string>,
  );
}

const placeholders = (text: string) => [...text.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]).sort();
const baseKeys = (flat: Record<string, string>) => new Set(Object.keys(flat).map((k) => k.replace(PLURAL_SUFFIX, "")));

describe.each(SUPPORTED_LANGUAGES)("%s", (language) => {
  const flat = flatten(CATALOGUES[language]);
  const english = flatten(en);

  it("has a catalogue", () => {
    expect(CATALOGUES[language]).toBeTruthy();
  });

  it("translates every English key and nothing else", () => {
    expect([...baseKeys(flat)].sort()).toEqual([...baseKeys(english)].sort());
  });

  it("has every plural form the language needs", () => {
    const categories = new Intl.PluralRules(intlLocale(language)).resolvedOptions().pluralCategories;
    const pluralKeys = new Set(
      Object.keys(english).filter((k) => PLURAL_SUFFIX.test(k)).map((k) => k.replace(PLURAL_SUFFIX, "")),
    );
    for (const key of pluralKeys) {
      for (const category of categories) {
        expect(flat, `${key}_${category}`).toHaveProperty([`${key}_${category}`]);
      }
    }
  });

  it("keeps every placeholder", () => {
    for (const [key, text] of Object.entries(flat)) {
      const englishText = english[key] ?? english[key.replace(PLURAL_SUFFIX, "_other")];
      expect(placeholders(text), key).toEqual(placeholders(englishText));
    }
  });

  it("uses the server's SEO text for the same pages", () => {
    // The server writes these into the HTML head before the app runs (app/seo.py);
    // the app must not then replace them with different words.
    const server = JSON.parse(
      readFileSync(resolve(__dirname, `../../../app/i18n/locales/${language}.json`), "utf-8"),
    ) as { seo: Record<string, string> };
    for (const [key, text] of Object.entries((CATALOGUES[language] as { seo: Record<string, string> }).seo)) {
      expect(text, key).toBe(server.seo[key]);
    }
  });
});
