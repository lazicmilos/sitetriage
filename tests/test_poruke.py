"""Statičko testiranje rečenica za klijenta — recenzija pretvorena u testove.

Rečenica ide pravo u mejl, pa mora biti tačna i pravilna, na oba jezika. Pravila:
svaki broj potiče iz dokaza (BUG-013), ispravljene netačne tvrdnje se ne vraćaju,
broj i imenica se slažu (BUG-014), a decimalni separator je onaj iz jezika (BUG-015).
Rečenice žive u katalogu (`skener.messages`), a nalaz nosi samo dokaz.
"""

from __future__ import annotations

import json
import re

import pytest
from factories import clean_browser, clean_site, run_level
from poruke_slucajevi import GOLDEN, slucajevi

from skener.checks import registry
from skener.messages import LANGS, catalog, reason, render
from skener.messages.en import plural as en_oblik
from skener.messages.sr import sa_brojem

registry.load_all()
SPECS = sorted(registry.REGISTRY.values(), key=lambda s: s.check_id)
SLUCAJEVI = list(slucajevi())


def sabloni(lang: str) -> list[tuple[str, str]]:
    """Svi klijentski šabloni jezika, sa varijantama."""
    out = []
    for check_id, entry in sorted(catalog(lang).FINDINGS.items()):
        out.append((check_id, entry["client"]))
        varijante = entry.get("variants", {}).items()
        out += [(f"{check_id}/{v}", o["client"]) for v, o in varijante if "client" in o]
    return out


SVI_SABLONI = [pytest.param(lang, s, id=f"{lang}-{ime}") for lang in LANGS for ime, s in sabloni(lang)]


# --------------------------------------------------------------------------- #
# Katalog
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_katalog_je_potpun_za_svaki_jezik(lang):
    """Svaka provera ima obe rečenice na svakom jeziku, i nijedan jezik nema višak."""
    cat, sr = catalog(lang), catalog("sr")
    assert set(cat.FINDINGS) == set(registry.REGISTRY), "katalog i registar se razilaze"
    for check_id, entry in cat.FINDINGS.items():
        assert entry["client"].strip() and entry["tech"].strip(), check_id
        assert set(entry.get("variants", {})) == set(sr.FINDINGS[check_id].get("variants", {})), check_id
    assert set(cat.TEXT) == set(sr.TEXT)
    assert set(cat.CODES) == set(sr.CODES)
    assert set(cat.REASONS) == set(sr.REASONS)
    assert {f"requires.{ime}" for ime in registry.REQUIREMENTS} <= set(cat.REASONS)


def test_svaki_kod_razloga_iz_koda_postoji_u_katalogu():
    """Kod razloga je string u proveri; greška u kucanju bi se videla tek kad provera ne zna."""
    from pathlib import Path

    paket = Path(registry.__file__).parents[1]
    izvor = "".join(p.read_text(encoding="utf-8") for p in paket.rglob("*.py"))
    kodovi = set(re.findall(r'(?:unknown|not_applicable)\(\s*[\w.]+,\s*"([\w.]+)"', izvor))
    kodovi |= set(re.findall(r'Reason\("([\w.]+)"', izvor))
    assert len(kodovi) > 20, kodovi
    assert kodovi <= set(catalog("sr").REASONS), sorted(kodovi - set(catalog("sr").REASONS))


def test_srpski_razlozi_isti_kao_pre_prevodjenja():
    """Golden je napravljen kodom u kome su razlozi bili gotove srpske rečenice."""
    from poruke_slucajevi import GOLDEN_RAZLOZI, razlozi

    golden = json.loads(GOLDEN_RAZLOZI.read_text(encoding="utf-8"))
    sada = [{"slucaj": s, "provera": c, "razlog": reason(r, "sr")} for s, c, r in razlozi()]
    assert len(sada) == len(golden)
    for staro, novo in zip(golden, sada, strict=True):
        assert novo == staro


def test_razlozi_na_engleskom_nemaju_srpskih_reci():
    from poruke_slucajevi import razlozi

    for slucaj, _, r in razlozi():
        tekst = reason(r, "en")
        assert not re.search(r"[čćšžđ]|\b(nije|sajt|stranica|početna)\b", tekst), (slucaj, tekst)


def test_nepoznat_jezik_je_greska():
    with pytest.raises(ValueError, match="nepoznat jezik 'de'"):
        catalog("de")


def test_srpske_recenice_iste_kao_pre_refaktora():
    """Golden je napravljen kodom pre izdvajanja poruka iz provera (Z-12)."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    sada = [
        {"slucaj": s, "check_id": f.check_id, "severity": f.severity, **render(f, "sr").__dict__}
        for s, f in SLUCAJEVI
    ]
    assert len(sada) == len(golden)
    for staro, novo in zip(golden, sada, strict=True):
        assert novo == staro


# Stringovi sa razmakom i slovima smeju samo pod ovim ključevima: to nije naš jezik, nego
# podatak koji dolazi spolja. Sve ostalo je broj, logička vrednost ili tehnički kod.
SPOLJNI_TEKST = {
    # URL
    "stranica", "canonical", "najgora", "lanac",
    # sirova poruka greške
    "greska", "detalj", "primer",
    # tekst sa sajta
    "naslov", "opis",
}


def test_dokaz_ne_sadrzi_prirodni_jezik():
    """Rečenicu pravi katalog; dokaz sa „3 kopije" ne može da se prikaže na engleskom."""
    losi = []
    for slucaj, finding in SLUCAJEVI:
        for kljuc, vrednost in finding.evidence.items():
            for stavka in vrednost if isinstance(vrednost, list) else [vrednost]:
                recenica = isinstance(stavka, str) and " " in stavka and re.search(r"[^\W\d_]", stavka)
                if recenica and kljuc not in SPOLJNI_TEKST:
                    losi.append((slucaj, finding.check_id, kljuc, stavka))
    assert not losi, losi


# --------------------------------------------------------------------------- #
# Broj u rečenici potiče iz dokaza; netačne tvrdnje se ne vraćaju
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("lang", "sablon"), SVI_SABLONI)
def test_svaki_broj_u_recenici_potice_iz_dokaza(lang, sablon):
    """Broj upisan napamet („sekunda i po") ne sme u rečenicu za klijenta."""
    bez_mesta_za_dokaz = re.sub(r"\{[^}]*\}", "", sablon)
    bez_mesta_za_dokaz = re.sub(r"\bh1\b|\b4G\b", "", bez_mesta_za_dokaz)  # imena, ne brojevi
    assert not re.search(r"\d", bez_mesta_za_dokaz), bez_mesta_za_dokaz


@pytest.mark.parametrize(
    ("lang", "tvrdnja"),
    [
        pytest.param("sr", "sekunda i po", id="sr-izmisljen-broj"),
        pytest.param("sr", "Sve proverene", id="sr-sve-umesto-tri"),
        pytest.param("sr", "nasumičnu", id="sr-google-bira-nasumicno"),
        pytest.param("sr", "gola adresa", id="sr-og-title-bez-naslova"),
        pytest.param("sr", "prosečnoj mobilnoj", id="sr-spora-veza-kao-prosecna"),
        pytest.param("sr", "Pretraživaču nije jasno", id="sr-vise-h1-zbunjuje-google"),
        pytest.param("sr", "neograničen broj", id="sr-soft404-neograniceno"),
        pytest.param("sr", "najčešće na starijim", id="sr-konzola-stari-telefoni"),
        pytest.param("en", "second and a half", id="en-izmisljen-broj"),
        pytest.param("en", "All checked", id="en-sve-umesto-tri"),
        pytest.param("en", "random", id="en-google-bira-nasumicno"),
        pytest.param("en", "average mobile", id="en-spora-veza-kao-prosecna"),
        pytest.param("en", "confus", id="en-vise-h1-zbunjuje-google"),
        pytest.param("en", "unlimited", id="en-soft404-neograniceno"),
        pytest.param("en", "older phones", id="en-konzola-stari-telefoni"),
    ],
)
def test_ispravljena_netacna_tvrdnja_se_ne_vraca(lang, tvrdnja):
    assert not [ime for ime, s in sabloni(lang) if tvrdnja.lower() in s.lower()]


def test_usteda_od_kompresije_se_racuna_iz_velicine():
    """80 kB, na četvrtinu → 60 kB manje; na 0,6 MB/s to je 0,1 s, ne „sekunda i po"."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 80_000
    nalaz = run_level(1, site)["perf.compression.missing"].findings[0]
    assert nalaz.evidence["usteda_s"] == 0.1
    assert "0,1 s" in render(nalaz, "sr").client and "0.1 s" in render(nalaz, "en").client
    assert nalaz.severity == "low"


# --------------------------------------------------------------------------- #
# Broj i imenica: granične vrednosti pravila (1 | 2–4 | 5–20 | 11–14 | 21 | 22 | 111…)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "broj, ocekivano",
    [
        pytest.param(1, "1 stranica", id="gv-1"),
        pytest.param(2, "2 stranice", id="gv-2"),
        pytest.param(4, "4 stranice", id="gv-4"),
        pytest.param(5, "5 stranica", id="gv-5"),
        pytest.param(11, "11 stranica", id="gv-11-izuzetak"),
        pytest.param(12, "12 stranica", id="gv-12-izuzetak"),
        pytest.param(14, "14 stranica", id="gv-14-izuzetak"),
        pytest.param(15, "15 stranica", id="gv-15"),
        pytest.param(21, "21 stranica", id="gv-21"),
        pytest.param(22, "22 stranice", id="gv-22"),
        pytest.param(25, "25 stranica", id="ke-25"),
        pytest.param(0, "0 stranica", id="gv-0"),
        pytest.param(101, "101 stranica", id="gv-101"),
        pytest.param(111, "111 stranica", id="gv-111-izuzetak"),
        pytest.param(112, "112 stranica", id="gv-112-izuzetak"),
        pytest.param(122, "122 stranice", id="gv-122"),
    ],
)
def test_srpski_broj(broj, ocekivano):
    assert sa_brojem(broj, "stranica", "stranice", "stranica") == ocekivano


@pytest.mark.parametrize(
    "broj, ocekivano",
    [
        pytest.param(0, "0 pages", id="gv-0"),
        pytest.param(1, "1 page", id="gv-1"),
        pytest.param(2, "2 pages", id="gv-2"),
        pytest.param(11, "11 pages", id="gv-11"),
        pytest.param(21, "21 pages", id="gv-21"),
    ],
)
def test_engleski_broj(broj, ocekivano):
    """Engleski nema izuzetak za 11–14 ni za 21: samo 1 je jednina."""
    assert f"{broj} {en_oblik(broj, ['page', 'pages'])}" == ocekivano


@pytest.mark.parametrize(
    "lang, h1, ocekivano",
    [
        pytest.param("sr", 4, "4 glavna naslova", id="sr-paukal"),
        pytest.param("sr", 5, "5 glavnih naslova", id="sr-mnozina"),
        pytest.param("sr", 21, "21 glavni naslov", id="sr-jednina"),
        pytest.param("en", 4, "4 main headings", id="en-mnozina"),
        pytest.param("en", 21, "21 main headings", id="en-21-nije-jednina"),
    ],
)
def test_poruka_o_vise_h1_je_pravilna(lang, h1, ocekivano):
    browser = clean_browser()
    browser.dom.h1_count = h1
    poruka = render(run_level(2, browser)["seo.h1.multiple"].findings[0], lang).client
    assert ocekivano in poruka, poruka


@pytest.mark.parametrize(
    "lang, greske, ocekivano",
    [
        pytest.param("sr", 4, "4 JavaScript greške", id="sr-paukal"),
        pytest.param("sr", 7, "7 JavaScript grešaka", id="sr-mnozina"),
        pytest.param("sr", 21, "21 JavaScript grešku", id="sr-jednina-akuzativ"),
        pytest.param("en", 4, "4 JavaScript errors", id="en-mnozina"),
    ],
)
def test_poruka_o_greskama_u_konzoli_je_pravilna(lang, greske, ocekivano):
    browser = clean_browser()
    browser.console.errors = greske
    poruka = render(run_level(2, browser)["qa.console.errors"].findings[0], lang).client
    assert ocekivano in poruka, poruka


@pytest.mark.parametrize(
    "lang, zahteva, ocekivano",
    [
        pytest.param("sr", 101, "101 odvojeno preuzimanje", id="sr-jednina"),
        pytest.param("sr", 102, "102 odvojena preuzimanja", id="sr-paukal"),
        pytest.param("sr", 150, "150 odvojenih preuzimanja", id="sr-mnozina"),
        pytest.param("en", 101, "101 separate downloads", id="en-mnozina"),
    ],
)
def test_poruka_o_broju_zahteva_je_pravilna(lang, zahteva, ocekivano):
    browser = clean_browser()
    browser.network.requests_at_load = zahteva
    poruka = render(run_level(2, browser)["perf.request.count"].findings[0], lang).client
    assert ocekivano in poruka, poruka


def _isti(site, polje: str, broj: int) -> None:
    """`broj` stranica sa istom vrednošću, svaka u svojoj grupi putanja."""
    for i, page in enumerate(site.pages[:broj]):
        setattr(page, polje, "Ista vrednost na više stranica")
        page.final_url = "https://cist.rs/" if i == 0 else f"https://cist.rs/g{i}/strana"


@pytest.mark.parametrize(
    "lang, broj, ocekivano",
    [
        pytest.param("sr", 3, "kao 3 kopije iste stranice", id="sr-paukal"),
        pytest.param("sr", 5, "kao 5 kopija iste stranice", id="sr-mnozina"),
        pytest.param("en", 3, "like 3 copies of the same page", id="en-mnozina"),
    ],
)
def test_poruka_o_istom_naslovu_je_pravilna(lang, broj, ocekivano):
    site = clean_site()
    _isti(site, "title", broj)
    poruka = render(run_level(1, site)["seo.title.duplicate"].findings[0], lang).client
    assert ocekivano in poruka, poruka


@pytest.mark.parametrize(
    "lang, broj, ocekivano",
    [
        pytest.param("sr", 3, "između 3 stranice.", id="sr-paukal"),
        pytest.param("sr", 5, "između 5 stranica.", id="sr-mnozina"),
        pytest.param("en", 3, "tell the 3 pages apart.", id="en-mnozina"),
    ],
)
def test_poruka_o_istom_opisu_je_pravilna(lang, broj, ocekivano):
    site = clean_site()
    _isti(site, "meta_description", broj)
    poruka = render(run_level(1, site)["seo.description.duplicate"].findings[0], lang).client
    assert ocekivano in poruka, poruka


# --------------------------------------------------------------------------- #
# BUG-015: decimalni separator jezika („14,9 MB" na srpskom, „14.9 MB" na engleskom)
# --------------------------------------------------------------------------- #
def _tezina(ukupno: int, po_tipu: dict[str, int]):
    browser = clean_browser()
    browser.network.bytes_at_load = ukupno
    browser.network.bytes_by_type_at_load = po_tipu
    return run_level(2, browser)["perf.page.weight"].findings[0]


def test_brojevi_u_recenici_imaju_decimalni_zarez():
    nalaz = _tezina(14_900_000, {"image": 14_900_000})
    poruka = render(nalaz, "sr")
    assert "14,9 MB" in poruka.client and "4,8 Mb/s" in poruka.client
    assert nalaz.evidence["mb"] == 14.9, "dokaz ostaje broj; menja se samo zapis u rečenici"
    assert "14.9" in poruka.tech, "tehnički opis ostaje sa tačkom"


def test_decimalni_separator_po_jeziku():
    nalaz = _tezina(14_900_000, {"image": 14_900_000})
    assert "14.9 MB" in render(nalaz, "en").client and "4.8 Mb/s" in render(nalaz, "en").client
    assert "," not in re.sub(r", ", "", render(nalaz, "en").client), "engleski nema decimalni zarez"


@pytest.mark.parametrize(
    "lang, ocekivano",
    [
        pytest.param("sr", "prenosi 22 MB (video dodatno 8 MB)", id="sr"),
        pytest.param("en", "transfers 22 MB (plus 8 MB of video)", id="en"),
    ],
)
def test_ceo_broj_nema_nulu_iza_zareza(lang, ocekivano):
    nalaz = _tezina(30_000_000, {"media": 8_000_000, "image": 22_000_000})
    assert nalaz.variant == "video"
    assert ocekivano in render(nalaz, lang).client


# --------------------------------------------------------------------------- #
# Tačne vrednosti brojeva u rečenici — mutaciono testiranje je pokazalo da nijedan
# test ne proverava formulu, pa bi `/ 8` → `/ 9` prošlo neprimećeno.
# --------------------------------------------------------------------------- #
def test_sekunde_na_mobilnoj_vezi_se_racunaju_tacno():
    """14,9 MB na 0,6 MB/s = 24,83 s, plus 1 s režije = 25,8 s."""
    nalaz = _tezina(14_900_000, {"image": 14_900_000})
    assert nalaz.evidence["sekundi"] == 25.8
    assert nalaz.evidence["brzina"] == 4.8


def test_usteda_od_kompresije_tacna_vrednost():
    """1,2 MB HTML-a, četvrtina ostaje: 0,9 MB manje na 0,6 MB/s = 1,5 s."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 1_200_000
    assert run_level(1, site)["perf.compression.missing"].findings[0].evidence["usteda_s"] == 1.5


@pytest.mark.parametrize(
    "izvor, sr_tekst",
    [
        pytest.param("sitemap", "(uzorak: sitemap)", id="ke-sitemap"),
        pytest.param("links", "(uzorak: interni linkovi sa početne)", id="ke-linkovi"),
    ],
)
def test_dokaz_kaze_odakle_je_uzorak(izvor, sr_tekst):
    """Uzorak iz linkova je manje pouzdan od uzorka iz mape sajta (§4.4), pa to piše u dokazu."""
    site = clean_site(sample_source=izvor)
    _isti(site, "canonical_normalized", 3)
    nalaz = run_level(1, site)["seo.canonical.duplicate"].findings[0]
    assert nalaz.evidence["uzorak"] == izvor, "u dokazu je kod; tekst daje katalog"
    assert sr_tekst in render(nalaz, "sr").tech


@pytest.mark.parametrize(
    "lang, ocekivano, netacno",
    [
        pytest.param("sr", "se ni za 25 s nije do kraja učitala", "treba 25 s", id="sr"),
        pytest.param("en", "did not finish loading even in 25 s", "needs 25 s", id="en"),
    ],
)
def test_prekid_ucitavanja_ne_tvrdi_koliko_traje(lang, ocekivano, netacno):
    """Stranica koja ne stigne do `load` za 25 s ne učitava se 25 s nego duže, koliko ne znamo."""
    browser = clean_browser()
    browser.timing.reached = "timeout"
    browser.timing.load_ms = None
    nalaz = run_level(2, browser)["perf.load.time"].findings[0]
    poruka = render(nalaz, lang).client
    assert ocekivano in poruka and netacno not in poruka, poruka
