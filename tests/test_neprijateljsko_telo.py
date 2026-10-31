"""Telo odgovora sa tuđeg servera ima tvrdu granicu, i posle raspakivanja.

Prolaz skenira stotine sajtova koje ne kontrolišemo. Jedan od njih sme da pošalje gzip od
65 kB koji se raspakuje u 64 MB, telo koje se ne završava ili telo koje kaplje bajt po bajt,
ali ne sme da potroši memoriju mašine niti da zaustavi prolaz. Telo preko granice se seče, a
provera koja čita ceo HTML tada kaže `unknown` sa razlogom, ne tvrdi ništa o onome što nije
pročitano.
"""

from __future__ import annotations

import asyncio
import time
import tracemalloc

import pytest
from factories import run_level
from localserver import FakeSite, Response, bomb, endless, html
from test_fetch_http import scan

from sitetriage.config import get, load_config
from sitetriage.fetch.http import DomainBudget, Fetcher, fetch_site
from sitetriage.messages import reason, render
from sitetriage.models import DomainInput

KB = 1024
HTML_PREFIX = b"<!doctype html><html lang='sr'><head><title>Bomba</title></head><body><h1>Bomba</h1>"


def podrazumevana_granica() -> int:
    return get(load_config(), "http.max_body_kb") * KB


# --------------------------------------------------------------------------- #
# Podrazumevane granice ne menjaju rezultat na običnom sajtu
# --------------------------------------------------------------------------- #
def test_podrazumevane_granice_su_iznad_svih_pragova_za_html():
    """Granica je za neprijateljski sajt, a ne prag: običan HTML ostaje ceo (perf.html.size je 500 kB)."""
    cfg = load_config()
    granica = get(cfg, "http.max_body_kb") * KB
    assert granica >= 10 * get(cfg, "thresholds.perf.html_size_kb") * KB
    assert granica >= 10 * get(cfg, "escalation.raw_html_bytes")
    # Ista granica kao pre (10 MB), samo sada važi i za raspakovan `.xml.gz`.
    assert get(cfg, "sitemap.max_kb") * KB == 10 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Dekompresiona bomba u HTML-u
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_pg_html_bomba_se_sece_na_granici(encoding):
    """65 kB na žici, 64 MB raspakovano: početna se čita do `http.max_body_kb` i označava kao sečena."""
    telo = bomb(64 * 1024 * KB, encoding=encoding, prefix=HTML_PREFIX)
    assert len(telo) < 200 * KB
    pocetna = Response(telo, headers={"content-encoding": encoding}, encoded=True)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site)

    home = snapshot.home
    assert snapshot.entry.status == 200 and home.status == 200
    assert home.truncated is True
    assert home.html_bytes == podrazumevana_granica()
    assert home.title == "Bomba", "ono što je stiglo do granice se i dalje čita"


def test_pg_html_bomba_ne_zauzima_memoriju_preko_granice():
    """Vrh memorije prati granicu, ne raspakovanu veličinu: 1 MB granica, 64 MB bomba."""
    telo = bomb(64 * 1024 * KB, prefix=HTML_PREFIX)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["http"]["max_body_kb"] = 1024

    async def jedan_zahtev(url: str):
        async with Fetcher(cfg) as fetcher:
            return await fetcher.request(url, DomainBudget(5, 30), retries=0)

    with FakeSite(extra={"/": Response(telo, headers={"content-encoding": "gzip"}, encoded=True)}) as site:
        tracemalloc.start()
        try:
            outcome = asyncio.run(jedan_zahtev(f"{site.base_url}/"))
            _, vrh = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert outcome.ok and outcome.truncated
    assert len(outcome.body) == 1024 * KB
    assert vrh < 16 * 1024 * KB, f"vrh memorije {vrh} B za granicu od 1 MB"


def test_pg_bomba_u_preusmerenju_se_ne_raspakuje():
    """Telo odgovora koji preusmerava se ne čita: httpx bi ga inače ceo raspakovao pre sledećeg koraka."""
    preusmerenje = Response(
        bomb(64 * 1024 * KB),
        status=302,
        headers={"content-encoding": "gzip", "location": "/pocetna"},
        encoded=True,
    )
    with FakeSite(extra={"/": preusmerenje, "/pocetna": Response(html("Prava početna"))}) as site:
        tracemalloc.start()
        try:
            snapshot = scan(site, **{"http.max_body_kb": 1024})
            _, vrh = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert snapshot.home.title == "Prava početna"
    assert snapshot.entry.redirect_chain == [f"{site.base_url}/", f"{site.base_url}/pocetna"]
    assert vrh < 16 * 1024 * KB, f"vrh memorije {vrh} B za granicu od 1 MB"


# --------------------------------------------------------------------------- #
# Telo koje se ne završava
# --------------------------------------------------------------------------- #
def test_pg_beskonacno_telo_se_sece_a_prolaz_ide_dalje():
    """Server šalje bez kraja i bez Content-Length: čita se do granice, ostatak sajta se skenira."""
    with FakeSite(extra={"/": Response(chunks=endless(HTML_PREFIX + b" " * 65536))}) as site:
        started = time.monotonic()
        snapshot = scan(site, **{"http.max_body_kb": 256})
        trajanje = time.monotonic() - started

    assert snapshot.home.truncated and snapshot.home.html_bytes == 256 * KB
    assert snapshot.robots.status == 200, "posle sečene početne skeniranje se nastavlja"
    assert len(snapshot.pages) > 1
    assert trajanje < 15


def test_pg_telo_koje_kaplje_ima_ukupan_rok():
    """Bajt na svakih 0,2 s nikad ne okine rok za čitanje (10 s), pa važi `http.timeout_total_s`."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["http"]["timeout_total_s"] = 1

    async def prolaz(site: FakeSite):
        async with Fetcher(cfg) as fetcher:
            return await asyncio.wait_for(fetch_site(fetcher, DomainInput(domain=site.base_url)), 15)

    kap = Response(chunks=endless(b"x", pause=0.2))
    with FakeSite(extra={"/": kap}) as site:
        started = time.monotonic()
        snapshot = asyncio.run(prolaz(site))
        trajanje = time.monotonic() - started

    assert snapshot.entry.error_kind == "timeout"
    assert "http.timeout_total_s" in snapshot.entry.error_detail
    assert trajanje < 10, "ponavlja se jednom, pa su to dva roka od 1 s i pauza"


# --------------------------------------------------------------------------- #
# Granične vrednosti: tačno granica prolazi, granica + 1 se seče
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("encoding", [None, "gzip"], ids=["bez-kompresije", "gzip"])
@pytest.mark.parametrize(
    "visak, seceno",
    [
        pytest.param(-1, False, id="gv-granica-minus-1"),
        pytest.param(0, False, id="gv-tacno-granica"),
        pytest.param(1, True, id="gv-granica-plus-1"),
    ],
)
def test_gv_granica_tela(encoding, visak, seceno):
    granica = 64 * KB
    telo = HTML_PREFIX + b" " * (granica + visak - len(HTML_PREFIX))
    headers = {"content-encoding": encoding} if encoding else {}
    with FakeSite(extra={"/": Response(telo, headers=headers)}) as site:
        snapshot = scan(site, **{"http.max_body_kb": 64})

    assert snapshot.home.truncated is seceno
    assert snapshot.home.html_bytes == min(len(telo), granica)


# --------------------------------------------------------------------------- #
# Provere nad sečenom početnom ne tvrde ništa o onome što nije pročitano
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def secena_pocetna():
    """Početna sečena na 64 kB: naslov, opis i canonical bi mogli da budu posle granice."""
    telo = b"<!doctype html><html><body>" + b"<p>tekst</p>" * 20_000
    with FakeSite(extra={"/": Response(telo)}) as site:
        return scan(site, **{"http.max_body_kb": 64})


@pytest.mark.parametrize(
    "check_id",
    [
        "seo.title.missing",
        "seo.description.missing",
        "seo.canonical.missing",
        "seo.title.duplicate",
        "social.og.title.missing",
        "i18n.lang.missing",
        "i18n.lang.mismatch",
    ],
)
def test_provera_sadrzaja_secene_pocetne_je_unknown(secena_pocetna, check_id):
    rezultat = run_level(1, secena_pocetna)[check_id]
    assert rezultat.status == "unknown"
    assert rezultat.reason.code == "requires.home_complete"
    assert reason(rezultat.reason, "sr") and reason(rezultat.reason, "en")


def test_velicina_secene_pocetne_je_nalaz_bar_te_velicine(secena_pocetna):
    """Sečeno na 64 kB znači „više od 64 kB": to je i dalje istina, samo bez tačnog broja."""
    rezultati = run_level(1, secena_pocetna)
    nalaz = rezultati["perf.compression.missing"].findings[0]
    assert nalaz.variant == "truncated"
    assert "više od 64 kB" in render(nalaz, "sr").client
    assert "more than 64 kB" in render(nalaz, "en").client
    # Prag od 500 kB je iznad pročitanog, pa se ne zna da li je HTML prevelik.
    velicina = rezultati["perf.html.size"]
    assert velicina.status == "unknown" and velicina.reason.code == "body_truncated"
    assert "64 kB" in reason(velicina.reason, "sr")


def test_velicina_secene_pocetne_iznad_praga_je_nalaz():
    telo = b"<!doctype html><html><body>" + b"<p>tekst</p>" * 60_000
    with FakeSite(extra={"/": Response(telo)}) as site:
        snapshot = scan(site, **{"http.max_body_kb": 600})
    nalaz = run_level(1, snapshot)["perf.html.size"].findings[0]
    assert nalaz.variant == "truncated"
    assert "više od 600 kB" in render(nalaz, "sr").client
    assert "more than 600 kB" in render(nalaz, "en").client


# --------------------------------------------------------------------------- #
# .xml.gz mapa sajta koja se raspakuje preko granice
# --------------------------------------------------------------------------- #
def test_pg_sitemap_gz_bomba_nije_nalaz_da_mape_nema():
    """Mapa postoji, samo je prevelika: `infra.sitemap.missing` je `unknown`, ne nalaz."""
    robots = b"User-agent: *\nSitemap: {base}/sitemap.xml.gz\n"
    xml = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    gz = {"content-type": "application/gzip"}
    mapa = Response(bomb(64 * 1024 * KB, prefix=xml), headers=gz, encoded=True)
    with FakeSite(extra={"/sitemap.xml.gz": mapa}) as site:
        site.extra["/robots.txt"] = Response(robots.replace(b"{base}", site.base_url.encode()))
        snapshot = scan(site)

    assert snapshot.sitemap.status == 200
    assert snapshot.sitemap.urls == [] and snapshot.sitemap.truncated
    rezultat = run_level(1, snapshot)["infra.sitemap.missing"]
    assert rezultat.status == "unknown" and rezultat.reason.code == "sitemap_too_large"
    assert snapshot.sample_source == "links", "uzorak se dopunjava vezama sa početne"


# --------------------------------------------------------------------------- #
# Raspakivanje deo po deo: isto što i httpx, ali bez komada većeg od granice koraka
# --------------------------------------------------------------------------- #
def _raspakuj(encodings: list[str], data: bytes) -> bytes:
    from sitetriage.fetch.http import _Raspakivanje

    r = _Raspakivanje(encodings)
    return b"".join([*r.decode(data[:7]), *r.decode(data[7:]), *r.flush()])


SADRZAJ = HTML_PREFIX * 50


@pytest.mark.parametrize(
    "encodings, sazmi",
    [
        pytest.param(["gzip"], lambda d: zlib_sazmi(d, 31), id="gzip"),
        pytest.param(["deflate"], lambda d: zlib_sazmi(d, 15), id="deflate-zlib"),
        pytest.param(["deflate"], lambda d: zlib_sazmi(d, -15), id="deflate-sirov"),
        pytest.param(["identity"], lambda d: d, id="identity"),
        pytest.param(["br"], lambda d: d, id="nepoznato-ostaje-kako-je-stiglo"),
        pytest.param(["gzip", " Deflate"], lambda d: zlib_sazmi(zlib_sazmi(d, 31), 15), id="dva-sazimanja"),
    ],
)
def test_raspakivanje_kao_httpx(encodings, sazmi):
    assert _raspakuj(encodings, sazmi(SADRZAJ)) == SADRZAJ


def zlib_sazmi(data: bytes, wbits: int) -> bytes:
    import zlib

    sazimac = zlib.compressobj(9, zlib.DEFLATED, wbits)
    return sazimac.compress(data) + sazimac.flush()


def test_raspakivanje_ne_vraca_komad_veci_od_koraka():
    from sitetriage.fetch.http import RASPAKOVANO_ODJEDNOM, _Raspakivanje

    delovi = list(_Raspakivanje(["gzip"]).decode(bomb(8 * 1024 * KB)))
    assert sum(map(len, delovi)) == 8 * 1024 * KB
    assert max(map(len, delovi)) <= RASPAKOVANO_ODJEDNOM


def test_pg_pokvaren_gzip_je_greska_veze_kao_pre():
    """httpx je za pokvaren gzip dizao `DecodingError`, a to je vrsta `connection`."""
    telo = Response(b"nije gzip uopste", headers={"content-encoding": "gzip"}, encoded=True)
    with FakeSite(extra={"/": telo}) as site:
        snapshot = scan(site)
    assert snapshot.entry.error_kind == "connection"
    assert "DecodingError" in snapshot.entry.error_detail


def test_pg_beskonacan_niz_preusmerenja_je_i_dalje_too_many_redirects():
    """Preusmerenja se sada prate ručno; granica httpx-a (20 skokova) mora da ostane ista."""
    petlja = Response(status=302, headers={"location": "/"})
    with FakeSite(extra={"/": petlja}) as site:
        snapshot = scan(site)
    assert snapshot.entry.error_kind == "too_many_redirects"
    assert site.paths().count("/") == 21, "početni zahtev i 20 skokova, bez ponavljanja, kao pre"
