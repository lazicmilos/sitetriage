"""Static testing of client sentences: the review turned into tests.

A sentence goes straight into an email, so it must be accurate and grammatical, in both languages.
The rules: every number comes from the evidence (BUG-013), corrected false claims do not come
back, number and noun agree (BUG-014), and the decimal separator is the language's (BUG-015).
Sentences live in the catalog (`sitetriage.messages`), and a finding carries only evidence.
"""

from __future__ import annotations

import json
import os
import re

import pytest
from factories import clean_browser, clean_site, run_level
from poruke_slucajevi import GOLDEN, slucajevi

from sitetriage.checks import registry
from sitetriage.messages import LANGS, catalog, reason, render
from sitetriage.messages.en import plural as en_plural
from sitetriage.messages.sr import with_number

registry.load_all()
SPECS = sorted(registry.REGISTRY.values(), key=lambda s: s.check_id)
CASES = list(slucajevi())


def templates(lang: str) -> list[tuple[str, str]]:
    """Every client template of a language, with variants."""
    out = []
    for check_id, entry in sorted(catalog(lang).FINDINGS.items()):
        out.append((check_id, entry["client"]))
        variants = entry.get("variants", {}).items()
        out += [(f"{check_id}/{v}", o["client"]) for v, o in variants if "client" in o]
    return out


ALL_TEMPLATES = [pytest.param(lang, t, id=f"{lang}-{name}") for lang in LANGS for name, t in templates(lang)]


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_catalog_is_complete_for_every_language(lang):
    """Every check has both sentences in every language, and no language has extras."""
    cat, sr = catalog(lang), catalog("sr")
    assert set(cat.FINDINGS) == set(registry.REGISTRY), "the catalog and the registry disagree"
    for check_id, entry in cat.FINDINGS.items():
        assert entry["client"].strip() and entry["tech"].strip(), check_id
        assert set(entry.get("variants", {})) == set(sr.FINDINGS[check_id].get("variants", {})), check_id
    assert set(cat.TEXT) == set(sr.TEXT)
    assert set(cat.CODES) == set(sr.CODES)
    assert set(cat.REASONS) == set(sr.REASONS)
    assert {f"requires.{name}" for name in registry.REQUIREMENTS} <= set(cat.REASONS)


@pytest.mark.skipif("MUTANT_UNDER_TEST" in os.environ, reason="under mutmut the source also contains mutants")
def test_every_reason_code_in_the_code_is_in_the_catalog():
    """A reason code is a string in the check; a typo would show only when the check does not know."""
    from pathlib import Path

    package = Path(registry.__file__).parents[1]
    source = "".join(p.read_text(encoding="utf-8") for p in package.rglob("*.py"))
    codes = set(re.findall(r'(?:unknown|not_applicable)\(\s*[\w.]+,\s*"([\w.]+)"', source))
    codes |= set(re.findall(r'Reason\("([\w.]+)"', source))
    assert len(codes) > 20, codes
    assert codes <= set(catalog("sr").REASONS), sorted(codes - set(catalog("sr").REASONS))


def test_serbian_reasons_same_as_before_translation():
    """The golden file was made by code in which reasons were ready-made Serbian sentences."""
    from poruke_slucajevi import GOLDEN_RAZLOZI, razlozi

    golden = json.loads(GOLDEN_RAZLOZI.read_text(encoding="utf-8"))
    current = [{"slucaj": s, "provera": c, "razlog": reason(r, "sr")} for s, c, r in razlozi()]
    assert len(current) == len(golden)
    for old, new in zip(golden, current, strict=True):
        assert new == old


def test_english_reasons_have_no_serbian_words():
    from poruke_slucajevi import razlozi

    for case, _, r in razlozi():
        sentence = reason(r, "en")
        assert not re.search(r"[čćšžđ]|\b(nije|sajt|stranica|početna)\b", sentence), (case, sentence)


def test_unknown_language_is_an_error():
    with pytest.raises(ValueError, match="unknown language 'de'"):
        catalog("de")


def test_serbian_sentences_same_as_before_refactoring():
    """The golden file was made by code from before messages moved out of the checks (ADR-009)."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = [
        {"slucaj": s, "check_id": f.check_id, "severity": f.severity, **render(f, "sr").__dict__}
        for s, f in CASES
    ]
    assert len(current) == len(golden)
    for old, new in zip(golden, current, strict=True):
        assert new == old


# Strings with a space and letters are allowed only under these keys: this is not our language
# but data that comes from outside. Everything else is a number, a boolean or a technical code.
EXTERNAL_TEXT = {
    # URL
    "page", "canonical", "worst_image", "chain",
    # raw error message
    "error", "detail", "first_error",
    # text from the site
    "title", "description",
}


def test_evidence_contains_no_natural_language():
    """The catalog builds the sentence; evidence with „3 kopije" cannot be shown in English."""
    bad = []
    for case, finding in CASES:
        for key, value in finding.evidence.items():
            for item in value if isinstance(value, list) else [value]:
                sentence = isinstance(item, str) and " " in item and re.search(r"[^\W\d_]", item)
                if sentence and key not in EXTERNAL_TEXT:
                    bad.append((case, finding.check_id, key, item))
    assert not bad, bad


# --------------------------------------------------------------------------- #
# A number in a sentence comes from the evidence; false claims do not come back
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("lang", "template"), ALL_TEMPLATES)
def test_every_number_in_a_sentence_comes_from_the_evidence(lang, template):
    """A number written in by hand („sekunda i po") must not get into a client sentence."""
    without_placeholders = re.sub(r"\{[^}]*\}", "", template)
    without_placeholders = re.sub(r"\bh1\b|\b4G\b", "", without_placeholders)  # names, not numbers
    assert not re.search(r"\d", without_placeholders), without_placeholders


@pytest.mark.parametrize(
    ("lang", "claim"),
    [
        pytest.param("sr", "sekunda i po", id="sr-invented-number"),
        pytest.param("sr", "Sve proverene", id="sr-all-instead-of-three"),
        pytest.param("sr", "nasumičnu", id="sr-google-picks-at-random"),
        pytest.param("sr", "gola adresa", id="sr-og-title-without-title"),
        pytest.param("sr", "prosečnoj mobilnoj", id="sr-slow-connection-as-average"),
        pytest.param("sr", "Pretraživaču nije jasno", id="sr-several-h1-confuse-google"),
        pytest.param("sr", "neograničen broj", id="sr-soft404-unlimited"),
        pytest.param("sr", "najčešće na starijim", id="sr-console-older-phones"),
        pytest.param("en", "second and a half", id="en-invented-number"),
        pytest.param("en", "All checked", id="en-all-instead-of-three"),
        pytest.param("en", "random", id="en-google-picks-at-random"),
        pytest.param("en", "average mobile", id="en-slow-connection-as-average"),
        pytest.param("en", "confus", id="en-several-h1-confuse-google"),
        pytest.param("en", "unlimited", id="en-soft404-unlimited"),
        pytest.param("en", "older phones", id="en-console-older-phones"),
        pytest.param("sr", "vrati nazad", id="sr-tls-visitors-give-up"),
        pytest.param("sr", "prvo traži", id="sr-robots-every-search-engine"),
        pytest.param("en", "turn back", id="en-tls-visitors-give-up"),
        pytest.param("en", "asks for first", id="en-robots-every-search-engine"),
        # BUG-018: the console also counts blocked Mixed Content and resources that return 404.
        pytest.param("sr", "JavaScript greš", id="sr-console-is-not-only-javascript"),
        pytest.param("en", "JavaScript error", id="en-console-is-not-only-javascript"),
        # Catalog review, 2026-10-05.
        pytest.param("sr", "ne dira putanje", id="sr-robots-does-not-protect-home-or-probes"),
        pytest.param("en", "or touch paths", id="en-robots-does-not-protect-home-or-probes"),
        pytest.param("sr", "budžet potrošen pre nje", id="sr-home-is-the-first-request"),
        pytest.param("en", "budget spent before it", id="en-home-is-the-first-request"),
        pytest.param("sr", "verovatno crta", id="sr-h1-rarely-from-javascript"),
        pytest.param("en", "probably drawn", id="en-h1-rarely-from-javascript"),
        pytest.param("sr", "ne označava nijedan jezik", id="sr-en-EN-is-a-language"),
        pytest.param("en", "does not denote any language", id="en-en-EN-is-a-language"),
    ],
)
def test_corrected_false_claim_does_not_come_back(lang, claim):
    texts = templates(lang) + [*catalog(lang).TEXT.items(), *catalog(lang).REASONS.items()]
    assert not [name for name, t in texts if claim.lower() in t.lower()]


# Words that claim frequency or human behaviour (ADR-022). The list may grow.
UNSOURCED = {
    "sr": ("većina", "većinu", "najčešće", "uvek", "nikad", "svaki", "svi", "niko", "mnogi", "često"),
    "en": ("most", "usually", "always", "never", "every", "all", "nobody", "many", "often"),
}
# The only way for such a word to stay: {check_id: (word, justification or source)}.
EXCEPTIONS: dict[str, tuple[str, str]] = {}


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("check_id", sorted(registry.REGISTRY))
def test_sentence_does_not_claim_human_behaviour_without_a_source(lang, check_id):
    entry = catalog(lang).FINDINGS[check_id]
    texts = [entry["client"], entry["tech"]]
    texts += [t for variant in entry.get("variants", {}).values() for t in variant.values()]
    allowed = EXCEPTIONS.get(check_id, ("", ""))[0]
    for word in UNSOURCED[lang]:
        found = [t for t in texts if word != allowed and re.search(rf"\b{word}\b", t, re.IGNORECASE)]
        assert not found, f"“{word}” without a source: {found}"


def test_compression_saving_is_computed_from_the_size():
    """80 kB, down to a quarter → 60 kB less; at 0.6 MB/s that is 0.1 s, not „sekunda i po"."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 80_000
    finding = run_level(1, site)["perf.compression.missing"].findings[0]
    assert finding.evidence["saving_s"] == 0.1
    assert "0,1 s" in render(finding, "sr").client and "0.1 s" in render(finding, "en").client
    assert finding.severity == "low"


# --------------------------------------------------------------------------- #
# Number and noun: boundary values of the rule (1 | 2–4 | 5–20 | 11–14 | 21 | 22 | 111…)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "number, expected",
    [
        pytest.param(1, "1 stranica", id="gv-1"),
        pytest.param(2, "2 stranice", id="gv-2"),
        pytest.param(4, "4 stranice", id="gv-4"),
        pytest.param(5, "5 stranica", id="gv-5"),
        pytest.param(11, "11 stranica", id="gv-11-exception"),
        pytest.param(12, "12 stranica", id="gv-12-exception"),
        pytest.param(14, "14 stranica", id="gv-14-exception"),
        pytest.param(15, "15 stranica", id="gv-15"),
        pytest.param(21, "21 stranica", id="gv-21"),
        pytest.param(22, "22 stranice", id="gv-22"),
        pytest.param(25, "25 stranica", id="ke-25"),
        pytest.param(0, "0 stranica", id="gv-0"),
        pytest.param(101, "101 stranica", id="gv-101"),
        pytest.param(111, "111 stranica", id="gv-111-exception"),
        pytest.param(112, "112 stranica", id="gv-112-exception"),
        pytest.param(122, "122 stranice", id="gv-122"),
    ],
)
def test_serbian_number(number, expected):
    assert with_number(number, "stranica", "stranice", "stranica") == expected


@pytest.mark.parametrize(
    "number, expected",
    [
        pytest.param(0, "0 pages", id="gv-0"),
        pytest.param(1, "1 page", id="gv-1"),
        pytest.param(2, "2 pages", id="gv-2"),
        pytest.param(11, "11 pages", id="gv-11"),
        pytest.param(21, "21 pages", id="gv-21"),
    ],
)
def test_english_number(number, expected):
    """English has no exception for 11–14 nor for 21: only 1 is singular."""
    assert f"{number} {en_plural(number, ['page', 'pages'])}" == expected


@pytest.mark.parametrize(
    "lang, h1, expected",
    [
        pytest.param("sr", 4, "4 glavna naslova", id="sr-paucal"),
        pytest.param("sr", 5, "5 glavnih naslova", id="sr-plural"),
        pytest.param("sr", 21, "21 glavni naslov", id="sr-singular"),
        pytest.param("en", 4, "4 main headings", id="en-plural"),
        pytest.param("en", 21, "21 main headings", id="en-21-is-not-singular"),
    ],
)
def test_message_about_several_h1_is_grammatical(lang, h1, expected):
    browser = clean_browser()
    browser.dom.h1_count = h1
    message = render(run_level(2, browser)["seo.h1.multiple"].findings[0], lang).client
    assert expected in message, message


@pytest.mark.parametrize(
    "lang, errors, expected",
    [
        pytest.param("sr", 4, "prijavljuje 4 greške", id="sr-paucal"),
        pytest.param("sr", 7, "prijavljuje 7 grešaka", id="sr-plural"),
        pytest.param("sr", 21, "prijavljuje 21 grešku", id="sr-singular-accusative"),
        pytest.param("en", 4, "reports 4 errors", id="en-plural"),
    ],
)
def test_message_about_console_errors_is_grammatical(lang, errors, expected):
    browser = clean_browser()
    browser.console.errors = errors
    message = render(run_level(2, browser)["qa.console.errors"].findings[0], lang).client
    assert expected in message, message


@pytest.mark.parametrize(
    "lang, requests, expected",
    [
        pytest.param("sr", 101, "101 odvojeno preuzimanje", id="sr-singular"),
        pytest.param("sr", 102, "102 odvojena preuzimanja", id="sr-paucal"),
        pytest.param("sr", 150, "150 odvojenih preuzimanja", id="sr-plural"),
        pytest.param("en", 101, "101 separate downloads", id="en-plural"),
    ],
)
def test_message_about_request_count_is_grammatical(lang, requests, expected):
    browser = clean_browser()
    browser.network.requests_at_load = requests
    message = render(run_level(2, browser)["perf.request.count"].findings[0], lang).client
    assert expected in message, message


def _same(site, field: str, count: int) -> None:
    """`count` pages with the same value, each in its own path group."""
    for i, page in enumerate(site.pages[:count]):
        setattr(page, field, "Ista vrednost na više stranica")
        page.final_url = "https://cist.rs/" if i == 0 else f"https://cist.rs/g{i}/strana"


@pytest.mark.parametrize(
    "lang, count, expected",
    [
        pytest.param("sr", 3, "(„Ista vrednost na više stranica”), njih 3.", id="sr"),
        pytest.param("en", 3, "(“Ista vrednost na više stranica”), 3 of them.", id="en"),
    ],
)
def test_message_about_the_same_title_is_grammatical(lang, count, expected):
    site = clean_site()
    _same(site, "title", count)
    message = render(run_level(1, site)["seo.title.duplicate"].findings[0], lang).client
    assert expected in message, message


@pytest.mark.parametrize(
    "lang, count, expected",
    [
        pytest.param("sr", 3, "isti kratak opis za Google, njih 3.", id="sr"),
        pytest.param("en", 3, "the same short description for Google, 3 of them.", id="en"),
    ],
)
def test_message_about_the_same_description_is_grammatical(lang, count, expected):
    site = clean_site()
    _same(site, "meta_description", count)
    message = render(run_level(1, site)["seo.description.duplicate"].findings[0], lang).client
    assert expected in message, message


# --------------------------------------------------------------------------- #
# BUG-015: the decimal separator of the language („14,9 MB" in Serbian, "14.9 MB" in English)
# --------------------------------------------------------------------------- #
def _weight(total: int, by_type: dict[str, int]):
    browser = clean_browser()
    browser.network.bytes_at_load = total
    browser.network.bytes_by_type_at_load = by_type
    return run_level(2, browser)["perf.page.weight"].findings[0]


def test_numbers_in_a_sentence_have_a_decimal_comma():
    finding = _weight(14_900_000, {"image": 14_900_000})
    message = render(finding, "sr")
    assert "14,9 MB" in message.client and "4,8 Mb/s" in message.client
    assert finding.evidence["mb"] == 14.9, "the evidence stays a number; only the sentence notation changes"
    assert "14.9" in message.tech, "the technical description keeps the point"


def test_decimal_separator_by_language():
    finding = _weight(14_900_000, {"image": 14_900_000})
    assert "14.9 MB" in render(finding, "en").client and "4.8 Mb/s" in render(finding, "en").client
    assert "," not in re.sub(r", ", "", render(finding, "en").client), "English has no decimal comma"


@pytest.mark.parametrize(
    "lang, expected",
    [
        pytest.param("sr", "prenosi 22 MB (video dodatno 8 MB)", id="sr"),
        pytest.param("en", "transfers 22 MB (plus 8 MB of video)", id="en"),
    ],
)
def test_integer_has_no_zero_after_the_separator(lang, expected):
    finding = _weight(30_000_000, {"media": 8_000_000, "image": 22_000_000})
    assert finding.variant == "video"
    assert expected in render(finding, lang).client


# --------------------------------------------------------------------------- #
# Exact values of the numbers in a sentence: mutation testing showed that no test checked the
# formula, so `/ 8` → `/ 9` would pass unnoticed.
# --------------------------------------------------------------------------- #
def test_seconds_on_a_mobile_connection_are_computed_exactly():
    """14.9 MB at 0.6 MB/s = 24.83 s, plus 1 s overhead = 25.8 s."""
    finding = _weight(14_900_000, {"image": 14_900_000})
    assert finding.evidence["seconds"] == 25.8
    assert finding.evidence["speed_mbps"] == 4.8


def test_compression_saving_exact_value():
    """1.2 MB of HTML, a quarter remains: 0.9 MB less at 0.6 MB/s = 1.5 s."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 1_200_000
    assert run_level(1, site)["perf.compression.missing"].findings[0].evidence["saving_s"] == 1.5


@pytest.mark.parametrize(
    "source, sr_text",
    [
        pytest.param("sitemap", "(uzorak: sitemap)", id="ke-sitemap"),
        pytest.param("links", "(uzorak: interni linkovi sa početne)", id="ke-links"),
    ],
)
def test_evidence_says_where_the_sample_comes_from(source, sr_text):
    """A sample from links is less reliable than one from the sitemap, so the evidence says so."""
    site = clean_site(sample_source=source)
    _same(site, "canonical_normalized", 3)
    finding = run_level(1, site)["seo.canonical.duplicate"].findings[0]
    assert finding.evidence["sample"] == source, "the evidence holds a code; the catalog gives the text"
    assert sr_text in render(finding, "sr").tech


@pytest.mark.parametrize(
    "lang, expected, wrong",
    [
        pytest.param("sr", "se ni za 25 s nije do kraja učitala", "treba 25 s", id="sr"),
        pytest.param("en", "did not finish loading even in 25 s", "needs 25 s", id="en"),
    ],
)
def test_load_timeout_does_not_claim_how_long_it_takes(lang, expected, wrong):
    """A page that does not reach `load` within 25 s does not load in 25 s but longer, by how much
    we do not know."""
    browser = clean_browser()
    browser.timing.reached = "timeout"
    browser.timing.load_ms = None
    finding = run_level(2, browser)["perf.load.time"].findings[0]
    message = render(finding, lang).client
    assert expected in message and wrong not in message, message


@pytest.mark.parametrize(
    "lang, expected",
    [("sr", "Na simuliranoj vezi od 4,8 Mb/s"), ("en", "On a simulated 4.8 Mb/s connection")],
)
@pytest.mark.parametrize("reached, load_ms", [("load", 9_000), ("timeout", None)])
def test_load_time_names_the_simulated_connection(lang, expected, reached, load_ms):
    """Seconds hold for the connection they were measured under, so the sentence names it (ADR-010)."""
    browser = clean_browser()
    browser.timing.reached, browser.timing.load_ms = reached, load_ms
    finding = run_level(2, browser)["perf.load.time"].findings[0]
    assert expected in render(finding, lang).client
