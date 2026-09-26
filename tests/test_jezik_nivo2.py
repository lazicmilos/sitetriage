"""Z-25: jezik iz renderovanog teksta. Čitač ekrana čita stranicu posle JavaScript-a.

Kad je nivo 2 radio, sve tri i18n provere gledaju `lang` i tekst posle JS-a, a dokaz kaže odakle.
Bez nivoa 2, ili sa snimkom nivoa 2 iz 1.x, gledaju sirovi HTML, kao do sada.
"""

from __future__ import annotations

from factories import SRPSKI_TEKST, clean_browser, clean_site, run_level

from skener.messages import reason

I18N = ("i18n.lang.invalid", "i18n.lang.mismatch", "i18n.lang.missing")


def js_sajt(lang: str | None = None):
    """Sirovi HTML skoro prazan, jer tekst i `lang` postavlja JavaScript."""
    site = clean_site()
    site.home.text_sample, site.home.text_length, site.home.lang = "Učitavanje…", 11, lang
    return site


def renderovano(lang: str | None, tekst: str = SRPSKI_TEKST):
    browser = clean_browser()
    browser.dom.lang, browser.dom.text_sample, browser.dom.text_length = lang, tekst[:4000], len(tekst)
    return browser


def provere(site, browser=None):
    rezultati = run_level(1, site, browser=browser)
    return {check_id: rezultati[check_id] for check_id in I18N}


def test_jezik_iz_renderovanog_teksta_kad_sirovog_nema():
    rezultat = provere(js_sajt(), renderovano("en-US"))["i18n.lang.mismatch"]
    assert rezultat.status == "finding"
    assert rezultat.findings[0].evidence["lang"] == "en-US"
    assert rezultat.findings[0].evidence["duzina_teksta"] == len(SRPSKI_TEKST)


def test_bez_nivoa_2_ostaje_unknown():
    rezultat = provere(js_sajt())["i18n.lang.mismatch"]
    assert rezultat.status == "unknown" and rezultat.reason.code == "text_too_short"


def test_premalo_teksta_i_posle_js_a_kaze_to():
    rezultat = provere(js_sajt(), renderovano("sr", "Kratko."))["i18n.lang.mismatch"]
    assert rezultat.status == "unknown"
    assert "posle JavaScript-a" in reason(rezultat.reason)


def test_lang_postavljen_iz_js_nije_missing_kad_je_nivo_2_radio():
    rezultati = provere(js_sajt(lang=None), renderovano("sr"))
    assert {check_id: r.status for check_id, r in rezultati.items()} == dict.fromkeys(I18N, "ok")


def test_lang_koji_js_ne_postavi_je_missing_i_posle_nivoa_2():
    rezultat = provere(js_sajt(lang=None), renderovano(None))["i18n.lang.missing"]
    assert rezultat.status == "finding" and rezultat.findings[0].evidence["izvor"] == "nivo2"


def test_dokaz_kaze_izvor_teksta():
    bez = provere(js_sajt(lang="zxx"))["i18n.lang.invalid"].findings[0]
    sa = provere(js_sajt(lang="sr"), renderovano("zxx"))["i18n.lang.invalid"].findings[0]
    assert (bez.evidence["izvor"], sa.evidence["izvor"]) == ("sirovi_html", "nivo2")


def test_nivo_2_iz_1x_bez_teksta_koristi_sirovi_html():
    """Snimak nivoa 2 iz 1.x nema tekst ni `lang` posle JS-a; tada važi sirovo stanje, kao pre."""
    rezultat = provere(js_sajt(lang="en"), clean_browser())["i18n.lang.mismatch"]
    assert rezultat.status == "unknown" and rezultat.reason.code == "text_too_short"
