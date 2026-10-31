"""Language checks.

Serbian is recognised by the share of Cyrillic letters and the share of diacritics among Latin
letters: Serbian in Latin script has 2–5 % diacritics, English none.
"""

from __future__ import annotations

import re

from sitetriage.checks.registry import Context, check, finding, ok, unknown
from sitetriage.models import SiteSnapshot

BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
UNDETERMINED_CODES = {"zxx", "und", "xx"}
# `detect_language` sees only Cyrillic and č/ć/š/ž/đ, so it cannot tell Serbian from these languages.
SIMILAR_TO_SERBIAN = frozenset(
    {"sr", "sh", "cnr", "hr", "bs", "sl", "cs", "sk", "pl", "lt", "lv", "et", "vi",
     "ru", "uk", "be", "bg", "mk", "kk", "ky", "mn", "tg", "tt", "ba"}
)
DIACRITICS = frozenset("čćšžđČĆŠŽĐ")


def _is_cyrillic(ch: str) -> bool:
    """The whole Unicode Cyrillic block (U+0400–U+04FF)."""
    return "Ѐ" <= ch <= "ӿ"


def detect_language(text: str, cyr_ratio: float, dia_ratio: float) -> str:
    """Returns `sr` or `undetermined`, never `en`.

    English cannot be told apart from Serbian written without diacritics, and such
    sites exist. When you do not know, the check is `ok`, not a finding.
    """
    cyr = lat = dia = 0
    for ch in text:
        if _is_cyrillic(ch):
            cyr += 1
        elif ch.isalpha():
            lat += 1
            if ch in DIACRITICS:
                dia += 1
    if cyr + lat == 0:
        return "undetermined"
    if cyr / (cyr + lat) > cyr_ratio:
        return "sr"
    if lat and dia / lat > dia_ratio:
        return "sr"
    return "undetermined"


def _page_state(snapshot: SiteSnapshot, ctx: Context) -> tuple[str | None, str, int, str]:
    """(`lang`, text sample, text length, source) of the page a screen reader reads (ADR-017).

    After level 2 that is the rendered page: a `lang` set by JavaScript is on it, so
    "no tag" would be a false claim. Without level 2, or with a 1.x snapshot, the raw HTML applies.
    """
    b = ctx.browser
    if b is not None and b.status != "failed" and b.dom.text_length is not None:
        return b.dom.lang, b.dom.text_sample, b.dom.text_length, "rendered"
    home = snapshot.home
    return home.lang, home.text_sample, home.text_length, "raw_html"


def _raw_html_truncated(snapshot: SiteSnapshot, source: str) -> bool:
    """The raw HTML of the home page was cut at `http.max_body_kb`; after level 2 the browser page applies."""
    return source == "raw_html" and snapshot.home.truncated


def _lang_usable(lang: str | None) -> bool:
    """Whether it makes sense to compare this `lang` with the content."""
    if not lang:
        return False
    value = lang.strip()
    return bool(value) and value.lower() not in UNDETERMINED_CODES and bool(BCP47.match(value))


@check(
    "i18n.lang.missing",
    level=1,
    category="i18n",
    base_severity="medium",
    requires=["home"],
    description="<html> nema atribut lang.",
    threshold="atribut lang ne postoji",
)
def lang_missing(snapshot: SiteSnapshot, ctx: Context):
    lang, _, _, source = _page_state(snapshot, ctx)
    if _raw_html_truncated(snapshot, source):
        return unknown(lang_missing.spec, "requires.home_complete")
    if lang is not None:
        return ok(lang_missing.spec)
    return finding(
        lang_missing.spec,
        ctx,
        evidence={
            "page": snapshot.home.final_url or snapshot.home.url,
            "lang_tag_count": 0,
            "source": source,
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "i18n.lang.invalid",
    level=1,
    category="i18n",
    base_severity="medium",
    requires=["home"],
    description="Atribut lang postoji ali ne označava nijedan jezik.",
    threshold="lang ∈ {zxx, und, prazno} ili ne parsira kao BCP-47",
)
def lang_invalid(snapshot: SiteSnapshot, ctx: Context):
    lang, _, _, source = _page_state(snapshot, ctx)
    if _raw_html_truncated(snapshot, source):
        return unknown(lang_invalid.spec, "requires.home_complete")
    if lang is None or _lang_usable(lang):
        return ok(lang_invalid.spec)
    return finding(
        lang_invalid.spec,
        ctx,
        evidence={
            "page": snapshot.home.final_url or snapshot.home.url,
            "lang": lang,
            "code_length": len(lang.strip()),
            "source": source,
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "i18n.lang.mismatch",
    level=1,
    category="i18n",
    # medium, not high: Google determines the language from the content and does not use `lang`,
    # so the consequence is accessibility, not search ranking (ADR-022).
    base_severity="medium",
    requires=["home"],
    description="Sadržaj je pouzdano srpski, a lang oznaka govori drugo.",
    threshold=(
        "sadržaj prepoznat kao sr (ćirilica > 30 % ili dijakritici > 0,5 %) "
        "uz lang jezika koji se ne piše ćirilicom ni sa č/ć/š/ž/đ (nije sr, hr, bs, ru, mk, bg…)"
    ),
)
def lang_mismatch(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    lang, text, length, source = _page_state(snapshot, ctx)
    if _raw_html_truncated(snapshot, source):
        return unknown(lang_mismatch.spec, "requires.home_complete")
    min_text = ctx.th("thresholds.i18n.min_text_length")
    if length < min_text:
        # From the raw HTML this is also a signal to escalate to level 2: the content is probably
        # rendered by JS.
        reason = "text_too_short" if source == "raw_html" else "text_too_short_rendered"
        return unknown(lang_mismatch.spec, reason, length=length, threshold=min_text)
    # A missing or unusable tag is covered by the other two checks; `zxx` must
    # land in `invalid`, not here (the `hotel-planina.example` fixture).
    if not _lang_usable(lang):
        return ok(lang_mismatch.spec)

    cyr_ratio = ctx.th("thresholds.i18n.cyrillic_ratio")
    dia_ratio = ctx.th("thresholds.i18n.diacritic_ratio")
    detected = detect_language(text, cyr_ratio, dia_ratio)
    if detected != "sr" or lang.strip().lower().split("-")[0] in SIMILAR_TO_SERBIAN:
        return ok(lang_mismatch.spec)

    cyr = sum(1 for ch in text if _is_cyrillic(ch))
    lat = sum(1 for ch in text if ch.isalpha() and not _is_cyrillic(ch))
    dia = sum(1 for ch in text if ch in DIACRITICS)
    return finding(
        lang_mismatch.spec,
        ctx,
        evidence={
            "page": home.final_url or home.url,
            "lang": lang,
            "detected_language": detected,
            "cyrillic_share": round(cyr / (cyr + lat), 4) if cyr + lat else 0.0,
            "diacritic_share": round(dia / lat, 4) if lat else 0.0,
            "text_length": length,
            "source": source,
        },
        urls=[home.final_url or home.url],
    )
