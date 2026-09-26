"""Z-23: `seo.canonical.duplicate` broji samo stranice čiji canonical upućuje na drugu adresu.

Početna koja upućuje na sebe je ispravna. Ozbiljnost zavisi od udela takvih stranica u uzorku,
jer dve podstranice od sedam nisu isto što i ceo sajt (O-9).
"""

from __future__ import annotations

import pytest
from factories import clean_site, page, run_level

from skener.messages import render

POCETNA = "https://cist.rs/"


def sajt(ukupno: int, tudji: dict[int, str]):
    """`ukupno` uspešno dohvaćenih stranica, svaka u svojoj grupi putanja; `tudji[i]` je
    canonical i-te stranice (0 je početna). Ostale upućuju na sebe."""
    site = clean_site()
    site.pages = [site.home] + [page(f"https://cist.rs/g{i}/strana") for i in range(1, ukupno)]
    for i, cilj in tudji.items():
        site.pages[i].canonical_normalized = cilj
    site.sitemap.urls = [p.url for p in site.pages[1:]]
    return site


def canonical(site):
    return run_level(1, site)["seo.canonical.duplicate"]


def test_pocetna_koja_upucuje_na_sebe_se_ne_broji():
    rezultat = canonical(sajt(7, {1: POCETNA, 2: POCETNA}))
    assert rezultat.status == "finding"
    assert rezultat.findings[0].evidence["stranica"] == 2, "početna upućuje na sebe"


def test_dve_podstranice_od_sedam_daju_medium():
    nalaz = canonical(sajt(7, {1: POCETNA, 2: POCETNA})).findings[0]
    assert nalaz.severity == "medium"
    assert (nalaz.evidence["stranica"], nalaz.evidence["ukupno"]) == (2, 7)


def test_jedna_stranica_sa_tudjim_canonical_om_nije_nalaz():
    assert canonical(sajt(7, {1: POCETNA})).status == "ok"


@pytest.mark.parametrize(
    "tudjih, ozbiljnost",
    [
        pytest.param(39, "medium", id="gv-0,39"),
        pytest.param(40, "high", id="gv-0,40"),
        pytest.param(41, "high", id="gv-0,41"),
        pytest.param(59, "high", id="gv-0,59"),
        pytest.param(60, "critical", id="gv-0,60"),
    ],
)
def test_ozbiljnost_po_udelu(tudjih, ozbiljnost):
    site = sajt(100, dict.fromkeys(range(1, tudjih + 1), POCETNA))
    nalaz = canonical(site).findings[0]
    assert nalaz.severity == ozbiljnost
    assert nalaz.evidence["udeo"] == tudjih / 100


def test_paginacija_jednog_bloga_nije_nalaz():
    """Strane 2 i 3 bloga upućuju na prvu: to je jedna grupa putanja, ne ceo sajt."""
    site = sajt(7, {})
    for i, strana in ((1, 2), (2, 3)):
        site.pages[i].url = site.pages[i].final_url = f"https://cist.rs/blog?page={strana}"
        site.pages[i].canonical_normalized = "https://cist.rs/blog"
    assert canonical(site).status == "ok"


def test_canonical_koji_se_razlikuje_samo_po_normalizaciji_nije_tudji():
    """Početna dohvaćena kao `https://cist.rs?utm_source=fb`, sa canonical-om `https://cist.rs/`."""
    site = sajt(7, {1: POCETNA, 2: POCETNA})
    site.home.final_url = "https://cist.rs?utm_source=fb"
    site.home.canonical_normalized = POCETNA
    assert canonical(site).findings[0].evidence["stranica"] == 2


@pytest.mark.parametrize(
    "lang, ocekivano",
    [
        pytest.param("sr", "2 od 7 proverenih stranica sajta", id="sr"),
        pytest.param("en", "2 of the 7 checked pages", id="en"),
    ],
)
def test_recenica_kaze_koliko_od_koliko(lang, ocekivano):
    nalaz = canonical(sajt(7, {1: POCETNA, 2: POCETNA})).findings[0]
    assert ocekivano in render(nalaz, lang).client
