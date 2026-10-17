import json
from pathlib import Path

import pytest

from app.helpers.instruments import CATALOG, CRYPTO_CATEGORIES, STOCK_SECTORS, VENUES
from app.i18n import SUPPORTED_LANGUAGES, catalog, describe, label, t, validate_language

LOCALES = Path("app/i18n/locales")


def _keys(node, prefix=""):
    if isinstance(node, dict):
        return {k for key, value in node.items() for k in _keys(value, f"{prefix}{key}.")}
    return {prefix.rstrip(".")}


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_every_locale_has_exactly_the_english_keys(lang):
    assert _keys(catalog(lang)) == _keys(catalog("en"))


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_every_taxonomy_code_has_a_label(lang):
    data = catalog(lang)
    assert set(data["category"]) == set(CRYPTO_CATEGORIES)
    assert set(data["sector"]) == set(STOCK_SECTORS)
    assert set(data["venue"]) == set(VENUES)


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_templates_only_use_known_placeholders(lang):
    for group in ("description", "seo"):
        for key, text in catalog(lang)[group].items():
            # Formatting with every parameter must not raise (no typos like {nmae}).
            text.format(name="N", symbol="S", category="C", venue="V", description="D")


def test_locale_files_are_utf8_json_with_the_seven_languages():
    assert sorted(p.stem for p in LOCALES.glob("*.json")) == sorted(SUPPORTED_LANGUAGES)
    for path in LOCALES.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


def test_translation_falls_back_to_english_then_the_key():
    assert t("pl", "seo.breadcrumb_markets") == "Rynki"
    assert t("xx", "seo.breadcrumb_markets") == "Markets"
    assert t("pl", "no.such.key") == "no.such.key"


def test_labels_return_the_code_when_untranslated():
    assert label("de", "sector", "energy") == "Energie"
    assert label("de", "sector", "space_mining") == "space_mining"
    assert label("de", "sector", None) is None


@pytest.mark.parametrize("lang, expected", [
    ("en", "ORLEN S.A. (PKN.WA) is a listed company. Sector: Energy. Exchange: Warsaw Stock Exchange (GPW)."),
    ("pl", "ORLEN S.A. (PKN.WA) to spółka giełdowa. Sektor: Energetyka. "
           "Giełda: Giełda Papierów Wartościowych w Warszawie (GPW)."),
])
def test_stock_descriptions(lang, expected):
    assert describe(lang, name="ORLEN S.A.", symbol="PKN.WA", asset_class="stock",
                    category="energy", venue="GPW") == expected


def test_crypto_and_unclassified_descriptions():
    assert describe("en", name="Bitcoin", symbol="BTC", asset_class="crypto", category="currency", venue=None) \
        == "Bitcoin (BTC) is a cryptocurrency. Category: Digital currency."
    assert describe("en", name="FOO", symbol="FOO", asset_class="crypto", category=None, venue=None) == "FOO (FOO)."


@pytest.mark.parametrize("value, expected", [(None, "en"), ("", "en"), ("PL", "pl"), (" no ", "no")])
def test_validate_language(value, expected):
    assert validate_language(value) == expected


def test_validate_language_rejects_unsupported():
    with pytest.raises(ValueError):
        validate_language("xx")
