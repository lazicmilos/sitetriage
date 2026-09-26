"""Jezičke provere (§5, §5.1)."""

from __future__ import annotations

import re

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
NEODREDJEN_KOD = {"zxx", "und", "xx"}
DIJAKRITICI = frozenset("čćšžđČĆŠŽĐ")


def _is_cyrillic(ch: str) -> bool:
    """Ceo Unicode blok ćirilice (U+0400–U+04FF)."""
    return "Ѐ" <= ch <= "ӿ"


def detect_language(text: str, cyr_ratio: float, dia_ratio: float) -> str:
    """Vraća `sr` ili `neodređeno` — nikad `en` (§5.1, tačka 3).

    Engleski od srpskog pisanog bez dijakritika ne možeš da razlikuješ, a takvih
    sajtova ima. Kad ne znaš, provera je `ok`, ne nalaz.
    """
    cyr = lat = dia = 0
    for ch in text:
        if _is_cyrillic(ch):
            cyr += 1
        elif ch.isalpha():
            lat += 1
            if ch in DIJAKRITICI:
                dia += 1
    if cyr + lat == 0:
        return "neodređeno"
    if cyr / (cyr + lat) > cyr_ratio:
        return "sr"
    if lat and dia / lat > dia_ratio:
        return "sr"
    return "neodređeno"


def _stanje(snapshot: SiteSnapshot, ctx: Context) -> tuple[str | None, str, int, str]:
    """(`lang`, uzorak teksta, dužina teksta, izvor) stranice koju čita čitač ekrana (Z-25).

    Posle nivoa 2 to je stranica posle JS-a: `lang` koji postavi JavaScript jeste na njoj, pa bi
    „nema oznake" bila netačna tvrdnja. Bez nivoa 2, ili sa snimkom iz 1.x, važi sirovi HTML.
    """
    b = ctx.browser
    if b is not None and b.status != "failed" and b.dom.text_length is not None:
        return b.dom.lang, b.dom.text_sample, b.dom.text_length, "nivo2"
    home = snapshot.home
    return home.lang, home.text_sample, home.text_length, "sirovi_html"


def _lang_usable(lang: str | None) -> bool:
    """Ima li smisla porediti ovaj `lang` sa sadržajem."""
    if not lang:
        return False
    value = lang.strip()
    return bool(value) and value.lower() not in NEODREDJEN_KOD and bool(BCP47.match(value))


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
    lang, _, _, izvor = _stanje(snapshot, ctx)
    if lang is not None:
        return ok(lang_missing.spec)
    return finding(
        lang_missing.spec,
        ctx,
        evidence={"stranica": snapshot.home.final_url or snapshot.home.url, "lang_oznaka": 0, "izvor": izvor},
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
    lang, _, _, izvor = _stanje(snapshot, ctx)
    if lang is None or _lang_usable(lang):
        return ok(lang_invalid.spec)
    return finding(
        lang_invalid.spec,
        ctx,
        evidence={
            "stranica": snapshot.home.final_url or snapshot.home.url,
            "lang": lang,
            "duzina_koda": len(lang.strip()),
            "izvor": izvor,
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "i18n.lang.mismatch",
    level=1,
    category="i18n",
    # medium, ne high: Google jezik određuje iz sadržaja i `lang` ne koristi, pa je
    # posledica pristupačnost, ne pozicija u pretrazi (docs/izvestaj-testiranja-100.md, O-3).
    base_severity="medium",
    requires=["home"],
    description="Sadržaj je pouzdano srpski, a lang oznaka govori drugo.",
    threshold=(
        "sadržaj prepoznat kao sr (ćirilica > 30 % ili dijakritici > 0,5 %) "
        "uz lang koji ne počinje sa sr"
    ),
)
def lang_mismatch(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    lang, tekst, duzina, izvor = _stanje(snapshot, ctx)
    min_text = ctx.th("thresholds.i18n.min_text_length")
    if duzina < min_text:
        # Iz sirovog HTML-a ujedno i signal za eskalaciju na nivo 2 (§6): sadržaj se verovatno crta iz JS-a.
        razlog = "text_too_short" if izvor == "sirovi_html" else "text_too_short_rendered"
        return unknown(lang_mismatch.spec, razlog, duzina=duzina, prag=min_text)
    # Nedostajuću i neupotrebljivu oznaku pokrivaju druge dve provere; `zxx` mora
    # da padne u `invalid`, ne ovde (§12.4).
    if not _lang_usable(lang):
        return ok(lang_mismatch.spec)

    cyr_ratio = ctx.th("thresholds.i18n.cyrillic_ratio")
    dia_ratio = ctx.th("thresholds.i18n.diacritic_ratio")
    detected = detect_language(tekst, cyr_ratio, dia_ratio)
    if detected != "sr" or lang.lower().startswith("sr"):
        return ok(lang_mismatch.spec)

    cyr = sum(1 for ch in tekst if _is_cyrillic(ch))
    lat = sum(1 for ch in tekst if ch.isalpha() and not _is_cyrillic(ch))
    dia = sum(1 for ch in tekst if ch in DIJAKRITICI)
    return finding(
        lang_mismatch.spec,
        ctx,
        evidence={
            "stranica": home.final_url or home.url,
            "lang": lang,
            "prepoznat_jezik": detected,
            "cirilica_udeo": round(cyr / (cyr + lat), 4) if cyr + lat else 0.0,
            "dijakritici_udeo": round(dia / lat, 4) if lat else 0.0,
            "duzina_teksta": duzina,
            "izvor": izvor,
        },
        urls=[home.final_url or home.url],
    )
