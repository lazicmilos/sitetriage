"""Granične vrednosti i tabele odlučivanja za sve pragove iz README-a.

Svaki prag ima tri tačke: granica − 1, granica, granica + 1. Tu defekti žive: `>`
umesto `>=` pomera nalaz za jednu jedinicu i nijedan test „sa sredine" to ne vidi.
Oznake slučajeva: `gv-` granična vrednost, `ke-` klasa ekvivalencije, `tab-` kolona
tabele odlučivanja.
"""

from __future__ import annotations

import pytest
from factories import CONFIG, clean_browser, clean_site, run_level

from skener.fetch.http import DomainBudget
from skener.models import CheckResult, Finding, OversizedImage, Reason, Unknown
from skener.score import _status, build_report, escalation_reasons, select_for_level2


def nalaz(check_id: str, category: str, severity: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status="finding",
        findings=[
            Finding(
                domain="d.rs", check_id=check_id, level=1, category=category, severity=severity,
                evidence={"broj": 1},
            )
        ],
    )


# --------------------------------------------------------------------------- #
# Nivo 1
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "html_bytes, ocekivano",
    [
        pytest.param(51_199, "ok", id="gv-50kB-minus"),
        pytest.param(51_200, "ok", id="gv-50kB"),
        pytest.param(51_201, "finding", id="gv-50kB-plus"),
    ],
)
def test_kompresija_granica(html_bytes, ocekivano):
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = html_bytes
    assert run_level(1, site)["perf.compression.missing"].status == ocekivano


@pytest.mark.parametrize(
    "kodiranje, ocekivano",
    [
        pytest.param("gzip", "ok", id="ke-gzip"),
        pytest.param("br", "ok", id="ke-br"),
        pytest.param("zstd", "ok", id="ke-zstd"),
        pytest.param("deflate", "ok", id="ke-deflate"),
        pytest.param("GZIP", "ok", id="pg-velika-slova"),
        pytest.param("identity", "finding", id="ke-nekompresovano"),
        pytest.param("", "finding", id="ke-bez-zaglavlja"),
    ],
)
def test_kompresija_klase_kodiranja(kodiranje, ocekivano):
    site = clean_site()
    site.home.headers = {"content-encoding": kodiranje}
    site.home.html_bytes = 80_000
    assert run_level(1, site)["perf.compression.missing"].status == ocekivano


@pytest.mark.parametrize(
    "html_bytes, ocekivano",
    [
        pytest.param(511_999, "ok", id="gv-500kB-minus"),
        pytest.param(512_000, "ok", id="gv-500kB"),
        pytest.param(512_001, "finding", id="gv-500kB-plus"),
    ],
)
def test_velicina_html_granica(html_bytes, ocekivano):
    site = clean_site()
    site.home.html_bytes = html_bytes
    assert run_level(1, site)["perf.html.size"].status == ocekivano


@pytest.mark.parametrize(
    "skokova, ocekivano",
    [
        pytest.param(2, "ok", id="gv-3-minus"),
        pytest.param(3, "finding", id="gv-3"),
        pytest.param(4, "finding", id="gv-3-plus"),
    ],
)
def test_lanac_preusmerenja_granica(skokova, ocekivano):
    site = clean_site()
    site.entry.redirect_chain = [f"https://cist.rs/korak{i}" for i in range(skokova + 1)]
    assert run_level(1, site)["perf.redirect.chain"].status == ocekivano


def _isti_naslov(site, broj_stranica: int, broj_grupa: int) -> None:
    """`broj_stranica` stranica sa istim naslovom, raspoređenih u `broj_grupa` grupa putanja."""
    for i, page in enumerate(site.pages[:broj_stranica]):
        page.title = "Dobrodošli"
        grupa = "/" if i == 0 else f"/g{min(i, broj_grupa - 1)}"
        page.final_url = f"https://cist.rs{grupa}/strana{i}" if grupa != "/" else "https://cist.rs/"


@pytest.mark.parametrize(
    "stranica, grupa, ocekivano",
    [
        pytest.param(2, 2, "ok", id="gv-stranice-3-minus"),
        pytest.param(3, 3, "finding", id="gv-stranice-3"),
        pytest.param(4, 3, "finding", id="gv-stranice-3-plus"),
        pytest.param(4, 2, "ok", id="gv-grupe-3-minus"),
        pytest.param(5, 4, "finding", id="gv-grupe-3-plus"),
    ],
)
def test_duplikat_naslova_granice(stranica, grupa, ocekivano):
    site = clean_site()
    _isti_naslov(site, stranica, grupa)
    assert run_level(1, site)["seo.title.duplicate"].status == ocekivano


# --- jezik: tri praga (min. tekst, udeo ćirilice, udeo dijakritika) -----------
def _tekst(site, tekst: str, lang: str = "en") -> None:
    site.home.lang = lang
    site.home.text_sample = tekst
    site.home.text_length = len(tekst)


@pytest.mark.parametrize(
    "duzina, ocekivano",
    [
        pytest.param(399, "unknown", id="gv-400-minus"),
        pytest.param(400, "finding", id="gv-400"),
        pytest.param(401, "finding", id="gv-400-plus"),
    ],
)
def test_jezik_minimalan_tekst(duzina, ocekivano):
    site = clean_site()
    _tekst(site, ("č" * 5 + "a" * 95) * 5)
    site.home.text_length = duzina
    assert run_level(1, site)["i18n.lang.mismatch"].status == ocekivano


@pytest.mark.parametrize(
    "cirilicnih, ocekivano",
    [
        pytest.param(29, "ok", id="gv-30pct-minus"),
        pytest.param(30, "ok", id="gv-30pct"),
        pytest.param(31, "finding", id="gv-30pct-plus"),
    ],
)
def test_jezik_udeo_cirilice(cirilicnih, ocekivano):
    """Udeo ćirilice mora biti > 0,30 (od svih slova); latinica ovde nema dijakritike."""
    site = clean_site()
    _tekst(site, ("ж" * cirilicnih + "a" * (100 - cirilicnih)) * 5)
    assert run_level(1, site)["i18n.lang.mismatch"].status == ocekivano


@pytest.mark.parametrize(
    "dijakritika, ocekivano",
    [
        pytest.param(4, "ok", id="gv-0.5pct-minus"),
        pytest.param(5, "ok", id="gv-0.5pct"),
        pytest.param(6, "finding", id="gv-0.5pct-plus"),
    ],
)
def test_jezik_udeo_dijakritika(dijakritika, ocekivano):
    """Udeo dijakritika mora biti > 0,005 od latiničnih slova: 5 od 1000 nije dovoljno."""
    site = clean_site()
    _tekst(site, "č" * dijakritika + "a" * (1000 - dijakritika))
    assert run_level(1, site)["i18n.lang.mismatch"].status == ocekivano


@pytest.mark.parametrize(
    "lang, ocekivano",
    [
        pytest.param("sr", "ok", id="ke-vazeci-2-slova"),
        pytest.param("srp", "ok", id="ke-vazeci-3-slova"),
        pytest.param("sr-Latn-RS", "ok", id="ke-vazeci-sa-podoznakama"),
        pytest.param("s", "finding", id="gv-1-slovo"),
        pytest.param("serb", "finding", id="gv-4-slova"),
        pytest.param("", "finding", id="nv-prazno"),
        pytest.param("   ", "finding", id="nv-razmaci"),
        pytest.param("zxx", "finding", id="nv-zxx"),
        pytest.param("und", "finding", id="nv-und"),
        pytest.param("sr_RS", "finding", id="nv-podvlaka"),
    ],
)
def test_jezik_oznaka_klase(lang, ocekivano):
    site = clean_site()
    site.home.lang = lang
    assert run_level(1, site)["i18n.lang.invalid"].status == ocekivano


# --------------------------------------------------------------------------- #
# Nivo 2
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "zahteva, ocekivano",
    [
        pytest.param(100, None, id="gv-100"),
        pytest.param(101, "medium", id="gv-100-plus"),
        pytest.param(150, "medium", id="gv-150"),
        pytest.param(151, "high", id="gv-150-plus"),
    ],
)
def test_broj_zahteva_granice(zahteva, ocekivano):
    browser = clean_browser()
    browser.network.requests_at_load = zahteva
    rezultat = run_level(2, browser)["perf.request.count"]
    assert (rezultat.findings[0].severity if rezultat.findings else None) == ocekivano


@pytest.mark.parametrize(
    "load_ms, ocekivano",
    [
        pytest.param(4000, None, id="gv-4s"),
        pytest.param(4001, "medium", id="gv-4s-plus"),
        pytest.param(8000, "medium", id="gv-8s"),
        pytest.param(8001, "high", id="gv-8s-plus"),
    ],
)
def test_vreme_ucitavanja_granice(load_ms, ocekivano):
    browser = clean_browser()
    browser.timing.load_ms = load_ms
    rezultat = run_level(2, browser)["perf.load.time"]
    assert (rezultat.findings[0].severity if rezultat.findings else None) == ocekivano


@pytest.mark.parametrize(
    "nemereno, ocekivano",
    [
        pytest.param(5, "ok", id="gv-5"),
        pytest.param(6, "unknown", id="gv-5-plus"),
    ],
)
def test_nemereni_odgovori_granica(nemereno, ocekivano):
    browser = clean_browser()
    browser.network.unmeasured_at_load = nemereno
    assert run_level(2, browser)["perf.page.weight"].status == ocekivano


@pytest.mark.parametrize(
    "h1, ocekivano",
    [
        pytest.param(3, "ok", id="gv-3"),
        pytest.param(4, "finding", id="gv-3-plus"),
    ],
)
def test_vise_h1_granica(h1, ocekivano):
    browser = clean_browser()
    browser.dom.h1_count = h1
    assert run_level(2, browser)["seo.h1.multiple"].status == ocekivano


@pytest.mark.parametrize(
    "gresaka, ocekivano",
    [
        pytest.param(3, "ok", id="gv-3"),
        pytest.param(4, "finding", id="gv-3-plus"),
    ],
)
def test_greske_u_konzoli_granica(gresaka, ocekivano):
    browser = clean_browser()
    browser.console.errors = gresaka
    assert run_level(2, browser)["qa.console.errors"].status == ocekivano


def _prevelike(broj: int, visak_kb: float) -> list[OversizedImage]:
    return [
        OversizedImage(src=f"https://cist.rs/s{i}.jpg", natural=[2000, 1000], client=[200, 100],
                       ratio=10.0, est_waste_kb=visak_kb / broj)
        for i in range(broj)
    ]


@pytest.mark.parametrize(
    "broj, visak_kb, ocekivano",
    [
        pytest.param(2, 100, "ok", id="gv-3-slike-minus"),
        pytest.param(3, 100, "finding", id="gv-3-slike"),
        pytest.param(1, 700, "ok", id="gv-700kB"),
        pytest.param(1, 701, "finding", id="gv-700kB-plus"),
    ],
)
def test_predimenzionirane_slike_granice(broj, visak_kb, ocekivano):
    browser = clean_browser()
    browser.dom.oversized_images = _prevelike(broj, visak_kb)
    assert run_level(2, browser)["perf.img.oversized"].status == ocekivano


@pytest.mark.parametrize(
    "ukupno, bez_alta, delatnost, ocekivano",
    [
        pytest.param(4, 4, "ostalo", None, id="gv-5-slika-minus"),
        pytest.param(5, 5, "ostalo", "low", id="gv-5-slika"),
        pytest.param(10, 5, "ostalo", None, id="gv-udeo-0.5"),
        pytest.param(10, 6, "ostalo", "low", id="gv-udeo-0.5-plus"),
        pytest.param(15, 12, "ostalo", "low", id="gv-udeo-0.8"),
        pytest.param(15, 13, "ostalo", "high", id="gv-udeo-0.8-plus"),
        pytest.param(14, 14, "ostalo", "low", id="gv-15-slika-minus"),
        pytest.param(15, 15, "ostalo", "high", id="gv-15-slika"),
        pytest.param(10, 6, "zdravstvo", "medium", id="ke-zdravstvo"),
        pytest.param(10, 6, "institucija", "medium", id="ke-institucija"),
        pytest.param(10, 6, "hotel", "low", id="ke-ostale-delatnosti"),
    ],
)
def test_alt_granice_i_delatnosti(ukupno, bez_alta, delatnost, ocekivano):
    browser = clean_browser()
    browser.dom.images_total = ukupno
    browser.dom.images_without_alt_attr = bez_alta
    browser.dom.images_empty_alt = 0
    rezultat = run_level(2, browser, industry=delatnost)["a11y.img.alt.missing"]
    assert (rezultat.findings[0].severity if rezultat.findings else None) == ocekivano


# --------------------------------------------------------------------------- #
# Politika eskalacije (§6): šest uslova vezanih sa ILI. Tabela odlučivanja po
# MC/DC — svaki uslov sam menja ishod — plus granične vrednosti tri praga.
# --------------------------------------------------------------------------- #
def _kvar(site, uslov: str) -> list:
    if uslov == "prazan-html":
        site.home.text_length = 799
    elif uslov == "nema-h1":
        site.home.h1_count_raw = 0
    elif uslov == "nalaz-medium":
        site.home.meta_description = None
    elif uslov == "veliki-html":
        site.home.html_bytes = 300_001
    elif uslov == "nekompresovan":
        site.home.headers = {}
        site.home.html_bytes = 60_000
    elif uslov == "spora-pocetna":
        site.entry.elapsed_ms = 1501
    return list(run_level(1, site).values())


@pytest.mark.parametrize(
    "uslov, trag",
    [
        pytest.param("prazan-html", "raw_text_short", id="tab-prazan-html"),
        pytest.param("nema-h1", "no_h1_raw", id="tab-nema-h1"),
        pytest.param("nalaz-medium", "medium_finding", id="tab-nalaz-medium"),
        pytest.param("veliki-html", "html_large", id="tab-veliki-html"),
        pytest.param("nekompresovan", "html_uncompressed", id="tab-nekompresovan"),
        pytest.param("spora-pocetna", "slow_entry", id="tab-spora-pocetna"),
    ],
)
def test_eskalacija_svaki_uslov_sam_menja_ishod(uslov, trag):
    site = clean_site()
    razlozi = escalation_reasons(site, _kvar(site, uslov), CONFIG)
    assert razlozi and any(r.code == trag for r in razlozi), razlozi


def test_eskalacija_nijedan_uslov():
    site = clean_site()
    assert escalation_reasons(site, list(run_level(1, site).values()), CONFIG) == []


@pytest.mark.parametrize(
    "polje, vrednost, ide",
    [
        pytest.param("text_length", 799, True, id="gv-800-minus"),
        pytest.param("text_length", 800, False, id="gv-800"),
        pytest.param("html_bytes", 300_000, False, id="gv-300kB"),
        pytest.param("html_bytes", 300_001, True, id="gv-300kB-plus"),
        pytest.param("elapsed_ms", 1500, False, id="gv-1500ms"),
        pytest.param("elapsed_ms", 1501, True, id="gv-1500ms-plus"),
    ],
)
def test_eskalacija_granice(polje, vrednost, ide):
    site = clean_site()
    setattr(site.entry if polje == "elapsed_ms" else site.home, polje, vrednost)
    assert bool(escalation_reasons(site, [], CONFIG)) is ide


def test_nalaz_ozbiljnosti_low_nije_razlog_za_eskalaciju():
    """Klasa ekvivalencije ispod praga ozbiljnosti: `low` sam ne šalje na nivo 2."""
    site = clean_site()
    assert escalation_reasons(site, [nalaz("infra.robots.missing", "infra", "low")], CONFIG) == []


# --------------------------------------------------------------------------- #
# Status domena — tabela odlučivanja (ne radi, početna, unknown, budžet)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ne_radi, pocetna, unknown, budzet, ocekivano",
    [
        pytest.param(False, False, False, False, "failed", id="tab-nema-pocetne"),
        pytest.param(False, False, True, True, "failed", id="tab-nema-pocetne-sve-ostalo"),
        pytest.param(False, True, False, False, "scanned", id="tab-sve-u-redu"),
        pytest.param(False, True, True, False, "partial", id="tab-unknown"),
        pytest.param(False, True, False, True, "partial", id="tab-budzet"),
        pytest.param(False, True, True, True, "partial", id="tab-unknown-i-budzet"),
        pytest.param(True, False, False, False, "unreachable", id="tab-ne-radi"),
        pytest.param(True, False, True, True, "unreachable", id="tab-ne-radi-sve-ostalo"),
    ],
)
def test_status_domena_tabela(ne_radi, pocetna, unknown, budzet, ocekivano):
    site = clean_site()
    if not pocetna:
        site.pages.clear()
    site.budget.exhausted = budzet
    nalazi = [Finding("cist.rs", "infra.unreachable", 1, "infra", "critical")] if ne_radi else []
    nepoznati = [Unknown(check_id="seo.title.duplicate", reason=Reason("requires.pages"))] if unknown else []
    assert _status(site, nalazi, nepoznati) == ocekivano


# --------------------------------------------------------------------------- #
# Limit nivoa 2 — granica broja kandidata
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kandidata, izabrano",
    [
        pytest.param(2, 2, id="gv-limit-minus"),
        pytest.param(3, 3, id="gv-limit"),
        pytest.param(4, 3, id="gv-limit-plus"),
        pytest.param(0, 0, id="ke-bez-kandidata"),
    ],
)
def test_limit_nivoa_2_granice(kandidata, izabrano):
    config = {**CONFIG, "escalation": {**CONFIG["escalation"], "max_level2": 3}}
    kandidati = [
        (clean_site(domain=f"d{i}.rs"), [nalaz("seo.description.missing", "seo", "medium")])
        for i in range(kandidata)
    ]
    assert len(select_for_level2(kandidati, config)) == izabrano


# --------------------------------------------------------------------------- #
# Budžet po domenu — broj zahteva i vreme (§4.2)
# --------------------------------------------------------------------------- #
def test_budzet_zahteva_granica():
    budzet = DomainBudget(max_requests=16, max_seconds=40)
    dozvoljeni = [budzet.take() for _ in range(16)]
    assert all(dozvoljeni), "16. zahtev je još u budžetu"
    assert budzet.take() is False, "17. zahtev probija budžet"


@pytest.mark.parametrize(
    "proteklo, dozvoljen",
    [
        pytest.param(39.999, True, id="gv-40s-minus"),
        pytest.param(40.0, False, id="gv-40s"),
        pytest.param(40.001, False, id="gv-40s-plus"),
    ],
)
def test_budzet_vremena_granica(monkeypatch, proteklo, dozvoljen):
    sat = {"sada": 1000.0}
    monkeypatch.setattr("skener.fetch.http.time.monotonic", lambda: sat["sada"])
    budzet = DomainBudget(max_requests=16, max_seconds=40)
    sat["sada"] = 1000.0 + proteklo
    assert budzet.take() is dozvoljen


def test_unknown_ne_donosi_bodove_nego_status_partial():
    """Klasa `unknown`: ne sme da se pretvori u bodove, ali mora da se vidi u statusu."""
    site = clean_site()
    nepoznat = CheckResult(check_id="seo.title.duplicate", status="unknown", reason=Reason("requires.pages"))
    izvestaj = build_report(site, [nepoznat], CONFIG)
    assert izvestaj.findings == [] and izvestaj.total_score == 0
    assert izvestaj.status == "partial"
    assert [u.check_id for u in izvestaj.unknowns] == ["seo.title.duplicate"]
