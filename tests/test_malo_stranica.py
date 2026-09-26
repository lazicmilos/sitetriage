"""Z-21: provere duplikata „ne primenjuju se" samo kad sajt stvarno ima < 3 stranice.

Mali uzorak nije isto što i mali sajt: uzorak je mali i kad budžet istekne, kad su veze u
JS-u i kad mapa sajta ne navodi sve stranice. Tada je `unknown`, a razlog kaže zašto.
"""

from __future__ import annotations

import asyncio

import pytest
from factories import clean_browser, clean_site, run_level
from localserver import FakeSite, Response

from skener.config import load_config
from skener.fetch.http import Fetcher, fetch_site
from skener.messages import reason
from skener.models import CheckResult, DomainInput
from skener.report import html_out
from skener.score import analyze

DUPLIKATI = ("seo.canonical.duplicate", "seo.description.duplicate", "seo.title.duplicate")


def mali_sajt(*, budzet: bool = False, adresa: int = 2, js: bool = True):
    """Početna i `/usluge` u uzorku; `adresa` je koliko različitih adresa vide izvori, sa početnom."""
    site = clean_site(pages=clean_site().pages[:2])
    podstrane = ["https://cist.rs/usluge"] + [f"https://cist.rs/strana-{i}" for i in range(2, adresa)]
    site.sitemap.urls = podstrane
    site.home_links = ["https://cist.rs/", "https://cist.rs/usluge"]
    site.budget.exhausted = budzet
    if not js:
        site.home.text_length = 100
        site.home.h1_count_raw = 0
    return site


def _duplikati(site, browser=None) -> dict[str, CheckResult]:
    rezultati = run_level(1, site, browser=browser)
    return {check_id: rezultati[check_id] for check_id in DUPLIKATI}


# --------------------------------------------------------------------------- #
# Tri uslova: budžet, broj adresa iz svih izvora, izvor koji vidi JS
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "budzet, adresa, js, status, razlog",
    [
        pytest.param(False, 2, True, "not_applicable", "few_pages", id="tab-sva-tri-ispunjena"),
        pytest.param(True, 2, True, "unknown", "pages_budget", id="tab-budzet-istekao"),
        pytest.param(False, 3, True, "unknown", "pages_sample", id="tab-izvori-vide-tri-adrese"),
        pytest.param(False, 2, False, "unknown", "pages_js", id="tab-niko-ne-vidi-js"),
        pytest.param(True, 5, False, "unknown", "pages_budget", id="tab-nista-nije-ispunjeno"),
    ],
)
def test_tri_uslova_za_ne_primenjuje_se(budzet, adresa, js, status, razlog):
    for check_id, rezultat in _duplikati(mali_sajt(budzet=budzet, adresa=adresa, js=js)).items():
        assert (rezultat.status, rezultat.reason.code) == (status, razlog), check_id


def test_nivo_2_vidi_js_kad_sirovi_html_ne_vidi():
    browser = clean_browser()
    browser.dom.internal_links = ["https://cist.rs/"]
    browser.dom.internal_links_total = 1
    for rezultat in _duplikati(mali_sajt(js=False), browser).values():
        assert rezultat.status == "not_applicable"


def test_veze_iz_renderovanog_doma_se_broje_u_adrese():
    browser = clean_browser()
    browser.dom.internal_links = ["https://cist.rs/a", "https://cist.rs/b"]
    browser.dom.internal_links_total = 2
    for rezultat in _duplikati(mali_sajt(), browser).values():
        assert (rezultat.status, rezultat.reason.code) == ("unknown", "pages_sample")


def test_nivo_2_bez_zabelezenih_veza_ne_vidi_js():
    """Snapshot nivoa 2 iz 1.x nema veze: nivo 2 je radio, ali njegove veze nisu viđene."""
    for rezultat in _duplikati(mali_sajt(js=False), clean_browser()).values():
        assert rezultat.reason.code == "pages_js"


def test_budzet_istekao_posle_pocetne_ostaje_unknown():
    site = mali_sajt(budzet=True)
    del site.pages[1:]
    izvestaj = analyze(site, load_config())
    assert izvestaj.status == "partial"
    assert {u.check_id for u in izvestaj.unknowns} >= set(DUPLIKATI)


def test_js_navigacija_bez_nivoa_2_ostaje_unknown():
    izvestaj = analyze(mali_sajt(js=False), load_config())
    assert izvestaj.status == "partial"
    assert {u.reason.code for u in izvestaj.unknowns if u.check_id in DUPLIKATI} == {"pages_js"}


def test_ne_primenjuje_se_ne_pravi_partial():
    izvestaj = analyze(mali_sajt(), load_config())
    assert izvestaj.status == "scanned" and not izvestaj.unknowns
    assert sorted(n.check_id for n in izvestaj.not_applicable) == sorted(DUPLIKATI)
    stranica = html_out.render([izvestaj], load_config())
    assert "ne primenjuje se: sajt ima 2 interne adrese" in stranica


def test_not_applicable_bez_razloga_je_bug():
    with pytest.raises(ValueError, match="bez `reason`"):
        CheckResult(check_id="seo.title.duplicate", status="not_applicable")


@pytest.mark.parametrize(
    "lang, ocekivano",
    [
        pytest.param("sr", "sajt ima 2 interne adrese, a za poređenje treba bar 3", id="sr"),
        pytest.param("en", "the site has 2 internal addresses, and a comparison needs at least 3", id="en"),
    ],
)
def test_razlog_ne_primenjuje_se_na_oba_jezika(lang, ocekivano):
    rezultat = _duplikati(mali_sajt())["seo.title.duplicate"]
    assert reason(rezultat.reason, lang) == ocekivano


def test_v1_snapshot_bez_veza_sa_pocetne_je_unknown():
    site = mali_sajt()
    site.scanner_version = "1.0.0"
    for rezultat in _duplikati(site).values():
        assert (rezultat.status, rezultat.reason.code) == ("unknown", "v1_snapshot")


# --------------------------------------------------------------------------- #
# Uzorkovanje: mala mapa sajta se dopunjava vezama sa početne
# --------------------------------------------------------------------------- #
def _skeniraj(site: FakeSite):
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=site.base_url))

    return asyncio.run(run())


def test_mapa_sa_dve_adrese_se_dopunjuje_vezama():
    def mapa(base: str) -> Response:
        adrese = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/usluge", "/kontakt"))
        xmlns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        return Response(f'<?xml version="1.0"?><urlset xmlns="{xmlns}">{adrese}</urlset>'.encode())

    class MalaMapa(FakeSite):
        def route(self, path: str) -> Response:
            return mapa(self.base_url) if path == "/sitemap.xml" else super().route(path)

    with MalaMapa() as site:
        snapshot = _skeniraj(site)
    putanje = sorted(p.url.removeprefix(site.base_url) for p in snapshot.pages)
    assert putanje == ["/", "/kontakt", "/o-nama", "/usluge"], "o-nama je samo u vezama sa početne"
    assert snapshot.home_links and all(link.startswith(site.base_url) for link in snapshot.home_links)
