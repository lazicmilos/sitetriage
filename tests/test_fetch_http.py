"""Integracioni testovi fetchera nivoa 1 protiv lokalnog servera.

Bez mreže ka spolja, ali sa pravim `httpx`-om, pravim semaforima i pravim
budžetom — jedino tako se §4.2, §4.6 i §8 zaista proveravaju.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import replace

import httpx
import pytest
from factories import run_level
from localserver import FakeSite, Response, html

from sitetriage import store
from sitetriage.config import load_config
from sitetriage.fetch.http import (
    DomainBudget,
    Fetcher,
    Outcome,
    _classify,
    _should_retry,
    fetch_site,
    probe_urls,
    scan_domains,
)
from sitetriage.messages import render
from sitetriage.models import DomainInput


def scan(site: FakeSite, **config_overrides) -> object:
    """Pauze su podrazumevano nula; test pristojnosti ih izričito uključuje."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    for dotted, value in config_overrides.items():
        section, _, key = dotted.rpartition(".")
        node = cfg
        for part in section.split("."):
            node = node[part]
        node[key] = value

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=site.base_url, industry="other"))

    return asyncio.run(run())


# --------------------------------------------------------------------------- #
# Pun prolaz
# --------------------------------------------------------------------------- #
def test_pun_prolaz_sklapa_snapshot():
    with FakeSite() as site:
        snapshot = scan(site)

    assert snapshot.entry.status == 200
    assert snapshot.robots.status == 200
    assert snapshot.sitemap.status == 200
    assert snapshot.sample_source == "sitemap"
    assert snapshot.home.title == "Početna"
    assert snapshot.home.raw_html, "sirovi HTML početne je potreban za eskalaciju i debug"
    assert all(p.raw_html is None for p in snapshot.pages[1:]), "sirovi HTML samo za početnu (§3.2)"
    assert len(snapshot.pages) >= 4
    assert len(snapshot.soft404.probes) == 2
    assert all(p.status == 404 for p in snapshot.soft404.probes)


def test_pocetna_koja_preusmerava_skriptom_je_skok_kao_http_preusmerenje():
    """BUG-022: stub od 95 B koji JavaScript-om vodi na /uskoro/ ocenjivan je kao početna."""
    stub = b"<html><head><script>location.replace('/uskoro/')</script></head><body></body></html>"
    uskoro = Response(html("Uskoro", body="<h1>Uskoro</h1>"))
    with FakeSite(extra={"/": Response(stub), "/uskoro/": uskoro}) as site:
        snapshot = scan(site)

    assert snapshot.home.title == "Uskoro"
    assert snapshot.home.final_url == f"{site.base_url}/uskoro/"
    assert snapshot.entry.redirect_chain == [f"{site.base_url}/", f"{site.base_url}/uskoro/"]
    assert snapshot.home.redirect_hops == 1
    assert run_level(1, snapshot)["seo.title.missing"].status == "ok"


def test_cist_lokalni_sajt_daje_malo_nalaza():
    """Kontrola protiv lažnih pozitiva nad sajtom koji je namerno uredan (U4)."""
    with FakeSite() as site:
        snapshot = scan(site)
    nalazi = {cid for cid, r in run_level(1, snapshot).items() if r.status == "finding"}
    assert nalazi <= {"infra.sitemap.missing"} or nalazi == set(), f"neočekivani nalazi: {nalazi}"


def test_rekurzija_kroz_sitemapindex():
    with FakeSite() as site:
        snapshot = scan(site)
    assert snapshot.sitemap.nested_count == 1
    assert snapshot.sitemap.depth_reached == 1
    assert any(url.endswith("/usluge") for url in snapshot.sitemap.urls)


def test_mape_drugih_domena_iz_robots_a_ne_trose_limit_fajlova():
    """robots.txt jednog lanca navodi mape svih sajtova lanca; ovaj sajt ima indeks sa podmapom."""
    tudje = "".join(f"Sitemap: https://lanac-{i}.test/sitemap.xml\n" for i in range(3))

    def robots():
        return Response(f"User-agent: *\nSitemap: {site.base_url}/sitemap.xml\n{tudje}".encode())

    with FakeSite(extra={"/robots.txt": robots}) as site:
        snapshot = scan(site)
    assert any(url.endswith("/usluge") for url in snapshot.sitemap.urls)


def test_robots_disallow_se_postuje():
    """Sitemap nudi /tajno/nesto; alat koji ga ipak traži je nekonzistentan (§4.3)."""
    with FakeSite() as site:
        snapshot = scan(site)
        trazeno = site.paths()
    assert any("/tajno/nesto" in url for url in snapshot.sitemap.urls), "sitemap ga jeste nudio"
    assert not any(path.startswith("/tajno") for path in trazeno), f"tražene putanje: {trazeno}"


def test_sitemap_direktiva_iz_robots_a_ima_prednost():
    with FakeSite() as site:
        scan(site)
        trazeno = site.paths()
    assert "/sitemap.xml" in trazeno


def test_sonde_su_deterministicke():
    """Isti domen mora da da iste sonde u svakom prolazu, inače testovi ne važe (§5.2)."""
    prvi = probe_urls("institucija.example", "https://institucija.example/")
    assert prvi == probe_urls("institucija.example", "https://institucija.example/")
    assert prvi != probe_urls("restoran-ugao.example", "https://restoran-ugao.example/")
    assert prvi[0].endswith("e3ce7e80ecbd5228") and prvi[1].endswith(".html")


def test_sonde_u_snapshotu_prate_cistu_funkciju():
    with FakeSite() as site:
        snapshot = scan(site)
        ocekivano = probe_urls(site.base_url, site.base_url)
    assert [p.url for p in snapshot.soft404.probes] == ocekivano


# --------------------------------------------------------------------------- #
# Pristojnost i konkurentnost (§8)
# --------------------------------------------------------------------------- #
def test_nikad_dva_paralelna_zahteva_ka_istom_hostu():
    """Po-hostu semafor je granica između alata i napada (§8.1)."""
    with FakeSite() as site:
        scan(site)
        assert site.concurrent_peak == 1, f"paralelnih ka istom hostu: {site.concurrent_peak}"


def test_pauza_izmedju_zahteva_ka_istom_hostu():
    with FakeSite() as site:
        import time

        started = time.monotonic()
        scan(site, **{"http.delay_ms": [120, 120], "http.max_requests_per_domain": 5})
        elapsed = time.monotonic() - started
    assert elapsed >= 0.4, f"pauze nisu ispoštovane, prolaz je trajao {elapsed:.2f} s"


def test_www_i_bez_www_dele_kljuc_pristojnosti():
    """Dva zahteva ka `www.x.rs` i `x.rs` idu jedan za drugim, sa pauzom između."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [100, 100]
    uporedo, najvise, pocetak = 0, 0, []

    class Sporo(Fetcher):
        async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
            nonlocal uporedo, najvise
            uporedo += 1
            najvise = max(najvise, uporedo)
            pocetak.append(time.monotonic())
            await asyncio.sleep(0.05)
            uporedo -= 1
            return Outcome(url=url, status=200, final_url=url)

    async def run():
        async with Sporo(cfg) as fetcher:
            budzet = DomainBudget(10, 30)
            www, bez = "https://www.primer.rs/", "https://primer.rs/"
            await asyncio.gather(fetcher.request(www, budzet), fetcher.request(bez, budzet))

    asyncio.run(run())
    assert najvise == 1
    assert pocetak[1] - pocetak[0] >= 0.1, "drugi zahtev čeka i pauzu pristojnosti"


def test_vise_domena_ide_paralelno():
    with FakeSite() as a, FakeSite() as b, FakeSite() as c:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        targets = [DomainInput(domain=s.base_url) for s in (a, b, c)]
        snapshots = asyncio.run(scan_domains(targets, cfg))
    assert len(snapshots) == 3
    assert all(s.entry.status == 200 for s in snapshots)


# --------------------------------------------------------------------------- #
# Budžet (§4.2)
# --------------------------------------------------------------------------- #
def test_budzet_zaustavlja_prolaz_a_ne_ruši_ga():
    with FakeSite() as site:
        snapshot = scan(site, **{"http.max_requests_per_domain": 3, "http.delay_ms": [0, 0]})
        trazeno = len(site.paths())

    assert trazeno <= 3, f"budžet probijen: {trazeno} zahteva"
    assert snapshot.budget.exhausted
    assert "budžet" in snapshot.budget.aborted_reason
    # Ono što je prikupljeno ide dalje, ostalo je `unknown` — ne pad.
    assert snapshot.entry.status == 200
    rezultati = run_level(1, snapshot)
    assert len(rezultati) == 22
    assert all(r.reason for r in rezultati.values() if r.status == "unknown")


def test_budzet_broji_i_vreme():
    budget = DomainBudget(max_requests=100, max_seconds=0)
    assert budget.take() is False
    assert "s" in budget.aborted_reason


# --------------------------------------------------------------------------- #
# Greške, ponovni pokušaji, odustajanje (§4.6, §8.3)
# --------------------------------------------------------------------------- #
def test_petsto_se_ponavlja_jednom_i_uspeva():
    pokusaji = {"broj": 0}

    def flaky() -> Response:
        pokusaji["broj"] += 1
        if pokusaji["broj"] == 1:
            return Response(b"greska", status=500)
        return Response(html("Usluge"))

    with FakeSite(extra={"/usluge": flaky}) as site:
        snapshot = scan(site)

    usluge = [p for p in snapshot.pages if p.url.endswith("/usluge")]
    assert pokusaji["broj"] == 2, "5xx se ponavlja tačno jednom (§4.6)"
    assert usluge and usluge[0].status == 200


def test_cetiristo_se_ne_ponavlja():
    pokusaji = {"broj": 0}

    def not_found() -> Response:
        pokusaji["broj"] += 1
        return Response(b"nema", status=404)

    with FakeSite(extra={"/usluge": not_found}) as site:
        scan(site)
    assert pokusaji["broj"] == 1, "4xx je odgovor, ne greška (§4.6)"


def test_na_429_se_odustaje_od_domena():
    with FakeSite(extra={"/robots.txt": Response(b"stani", status=429)}) as site:
        snapshot = scan(site)
        trazeno = site.paths()

    assert "429" in snapshot.budget.aborted_reason
    assert trazeno.count("/robots.txt") == 1, "na 429 se ne pokušava ponovo (§8.3)"
    assert len(trazeno) == 2, f"posle 429 nema daljih zahteva, a bilo ih je: {trazeno}"


def test_lazni_404_se_prepoznaje_kroz_ceo_lanac():
    with FakeSite(soft404=True) as site:
        snapshot = scan(site)

    assert all(p.status == 200 for p in snapshot.soft404.probes)
    result = run_level(1, snapshot)["infra.soft404"]
    assert result.status == "finding"
    assert result.findings[0].evidence["hard_evidence"] is True


def test_preusmerenja_se_belezе():
    with FakeSite(
        extra={
            "/": Response(b"", status=301, headers={"Location": "/korak1"}),
            "/korak1": Response(b"", status=301, headers={"Location": "/korak2"}),
            "/korak2": Response(b"", status=301, headers={"Location": "/kraj"}),
            "/kraj": Response(html("Kraj")),
        }
    ) as site:
        snapshot = scan(site)

    assert snapshot.entry.status == 200
    assert len(snapshot.entry.redirect_chain) == 4
    assert run_level(1, snapshot)["perf.redirect.chain"].status == "finding"


@pytest.mark.parametrize(
    "stop_at, trazeno, status", [("/", ["/stara", "/nova"], 302), ("/drugde", None, 200)]
)
def test_preusmerenje_na_vec_preuzetu_adresu_se_ne_prati(stop_at, trazeno, status):
    """Varijanta hosta staje pred početnom koja je već preuzeta; inače ide do kraja (Z-26)."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    with FakeSite(
        extra={
            "/stara": Response(b"", status=301, headers={"Location": "/nova"}),
            "/nova": Response(b"", status=302, headers={"Location": "/"}),
        }
    ) as site:
        b = site.base_url

        async def run():
            async with Fetcher(cfg) as fetcher:
                return await fetcher.request(f"{b}/stara", DomainBudget(5, 30), stop_at=f"{b}{stop_at}")

        outcome = asyncio.run(run())
        assert site.paths() == (trazeno or ["/stara", "/nova", "/"])
    assert (outcome.status, outcome.final_url) == (status, f"{b}/")
    assert outcome.redirect_chain == [f"{b}/stara", f"{b}/nova", f"{b}/"]


def merenje_veze(site: FakeSite, putanja: str, max_s: float = 5):
    from sitetriage.fetch.http import measure_link

    cfg = load_config()
    cfg["network_profile"] |= {"probe_url": f"{site.base_url}{putanja}", "probe_max_s": max_s}
    return asyncio.run(measure_link(cfg))


def test_merenje_veze_daje_brzinu():
    """Z-33: lokalni server je brži od svake stvarne veze."""
    with FakeSite(extra={"/proba.bin": Response(b"x" * 2_000_000)}) as site:
        assert merenje_veze(site, "/proba.bin") > 50


def test_merenje_veze_ima_tvrdi_rok():
    """Na sporoj vezi se meri koliko stigne za `probe_max_s`, a ne čeka se ceo fajl."""
    with FakeSite(extra={"/proba.bin": Response(b"x" * 2_000_000, stall=10)}) as site:
        started = time.monotonic()
        brzina = merenje_veze(site, "/proba.bin", max_s=1)
        assert time.monotonic() - started < 4
    assert brzina is not None and brzina < 1


@pytest.mark.parametrize(
    "odgovor", [None, Response(b"x", delay=3)], ids=["nema-fajla", "nijedan-bajt-za-rok"]
)
def test_neuspelo_merenje_veze_je_none(odgovor):
    with FakeSite(extra={"/proba.bin": odgovor} if odgovor else {}) as site:
        assert merenje_veze(site, "/proba.bin", max_s=1) is None


def test_kompresovan_odgovor_ne_pali_nalaz():
    with FakeSite(
        extra={"/": Response(html("Početna", body="x" * 80_000), headers={"content-encoding": "gzip"})}
    ) as site:
        snapshot = scan(site)
    assert snapshot.home.headers.get("content-encoding") == "gzip"
    assert run_level(1, snapshot)["perf.compression.missing"].status == "ok"


def test_nekompresovan_veliki_html_pali_nalaz():
    with FakeSite(extra={"/": Response(html("Početna", body="x" * 80_000))}) as site:
        snapshot = scan(site)
    assert run_level(1, snapshot)["perf.compression.missing"].status == "finding"


def test_fallback_na_interne_linkove_kad_nema_sitemapa():
    with FakeSite(
        extra={
            "/sitemap.xml": Response(b"nema", status=404),
            "/robots.txt": Response(b"nema", status=404),
        }
    ) as site:
        snapshot = scan(site)

    assert snapshot.sample_source == "links"
    assert any(p.url.endswith("/usluge") for p in snapshot.pages)
    assert run_level(1, snapshot)["infra.sitemap.missing"].status == "finding"
    assert run_level(1, snapshot)["infra.robots.missing"].status == "finding"


# --------------------------------------------------------------------------- #
# Klasifikacija izuzetaka — jedini deo §4.6 koji se ne može izazvati lokalno
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc, expected",
    [
        (httpx.ConnectError("x", request=None), "connection"),
        (httpx.ConnectTimeout("x", request=None), "connect_timeout"),
        (httpx.ReadTimeout("x", request=None), "read_timeout"),
        (httpx.TooManyRedirects("x", request=None), "too_many_redirects"),
    ],
)
def test_klasifikacija_izuzetaka(exc, expected):
    assert _classify(exc)[0] == expected


def test_dns_greska_se_prepoznaje_kroz_lanac_uzroka():
    try:
        try:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        except socket.gaierror as cause:
            raise httpx.ConnectError("greška", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "dns_nxdomain"


def test_istekao_sertifikat_je_tls_a_ne_pad():
    import ssl

    try:
        try:
            raise ssl.SSLCertVerificationError("certificate has expired")
        except ssl.SSLCertVerificationError as cause:
            raise httpx.ConnectError("greška", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "tls"


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (Outcome(url="u", status=404), False),
        (Outcome(url="u", status=500), True),
        (Outcome(url="u", status=200), False),
        (Outcome(url="u", error_kind="read_timeout"), True),
        (Outcome(url="u", error_kind="dns"), False),
        (Outcome(url="u", error_kind="dns_nxdomain"), False),
        # EAI_AGAIN je po definiciji privremen: hotspot ga je dao na svakom četvrtom domenu (prolaz F)
        (Outcome(url="u", error_kind="dns_temporary"), True),
        (Outcome(url="u", error_kind="tls"), False),
    ],
)
def test_politika_ponovnih_pokusaja(outcome, expected):
    assert _should_retry(outcome) is expected


def test_pokvaren_domen_ne_ruši_prolaz():
    """Ubacivanje namerno pokvarenog domena ne sme da obori ceo prolaz (§13, faza 3)."""
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        cfg["http"]["timeout_connect_s"] = 1
        targets = [
            DomainInput(domain=site.base_url),
            DomainInput(domain="http://127.0.0.1:1"),  # niko ne sluša
        ]
        snapshots = asyncio.run(scan_domains(targets, cfg))

    assert len(snapshots) == 2
    assert snapshots[0].entry.status == 200
    assert snapshots[1].entry.status is None
    assert run_level(1, snapshots[1]) and len(run_level(1, snapshots[1])) == 22


def test_snapshot_se_pise_na_disk_cim_je_domen_gotov(tmp_path):
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        asyncio.run(scan_domains([DomainInput(domain=site.base_url)], cfg, snapshot_dir=tmp_path))

    zapisani = list(tmp_path.glob("*/site.json"))
    assert len(zapisani) == 1, f"nije zapisano: {list(tmp_path.rglob('*'))}"
    ucitani = list(store.read_all(tmp_path))
    assert len(ucitani) == 1 and ucitani[0][0].entry.status == 200


@pytest.mark.parametrize(
    "domain, expected",
    [
        ("institucija.example", "institucija.example"),
        ("http://127.0.0.1:8123", "http_127.0.0.1_8123"),
        ("../../etc/passwd", "etc_passwd"),
        ("", "unknown-domain"),
    ],
)
def test_ime_direktorijuma_ne_izlazi_iz_izlaznog_foldera(domain, expected):
    """Domen dolazi iz korisnikovog CSV-a — granica poverenja."""
    assert store.slug(domain) == expected


# --------------------------------------------------------------------------- #
# Regresije iz revizije pred pravi prolaz — svaka je tiha na localhost-u, a
# glasna na 200 pravih domena.
# --------------------------------------------------------------------------- #
class SporSajt(FakeSite):
    """Svaki odgovor kasni — lokalni server inače odgovara za mikrosekunde."""

    def __init__(self, *, delay: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    def route(self, path: str) -> Response:
        return replace(super().route(path), delay=self.delay)


def test_budzet_vremena_krece_tek_kad_domen_dobije_red():
    """Budžet od 40 s je za rad na domenu, ne za čekanje u redu iza ostalih 199.

    Deset domena na dva mesta = pet krugova, pa je rad jednog domena oko petine
    prolaza. Da sat kreće za sve odjednom, poslednji domeni bi imali potrošeno
    skoro celo vreme prolaza. Poredi se odnos, ne apsolutno vreme, pa test ne zavisi
    od brzine mašine.
    """
    import time

    sajtovi = [SporSajt(delay=0.05) for _ in range(10)]
    for sajt in sajtovi:
        sajt.__enter__()
    try:
        cfg = load_config()
        cfg["http"].update(delay_ms=[0, 0], concurrency=2, domain_concurrency=2)
        targets = [DomainInput(domain=s.base_url) for s in sajtovi]
        pocetak = time.monotonic()
        snapshots = asyncio.run(scan_domains(targets, cfg))
        ukupno = time.monotonic() - pocetak
    finally:
        for sajt in sajtovi:
            sajt.__exit__()

    najduze = max(s.budget.elapsed_ms for s in snapshots) / 1000
    assert najduze < ukupno * 0.6, (
        f"domen je potrošio {najduze:.1f} s od {ukupno:.1f} s prolaza: sat je tekao dok je čekao red"
    )


def test_vreme_odgovora_ne_uključuje_pauzu_pristojnosti():
    """`elapsed_ms` je ono što server radi, ne ono što mi čekamo.

    Inače pravilo eskalacije „početna odgovara > 1500 ms" pali za svakoga ko je
    čekao u redu, i gubi smisao zbog kog postoji (b2b-firma.example).
    """
    with FakeSite() as site:
        # početna + robots + 2 mape + 2 sonde = 6; tek sedmi i osmi zahtev su uzorak
        snapshot = scan(site, **{"http.delay_ms": [600, 600], "http.max_requests_per_domain": 8})
    uzorak = snapshot.pages[1:]
    assert uzorak, "uzorak mora da ima bar jednu stranicu"
    # Pauza je 600 ms; lokalni odgovor traje desetak ms, a pod opterećenjem do ~300 ms.
    assert all(p.elapsed_ms < 450 for p in uzorak), [p.elapsed_ms for p in uzorak]


class IndexPhpSajt(FakeSite):
    """PHP sa PATH_INFO: `/index.php/bilo-sta` vraća 200, a pravi 404 radi."""

    def route(self, path: str) -> Response:
        if path == "/":
            return Response(b"", status=302, headers={"Location": "/index.php"})
        if path == "/index.php" or path.startswith("/index.php/"):
            return super().route("/")
        return super().route(path)


def test_sonde_idu_na_poreklo_a_ne_na_putanju_pocetne():
    """Sonda `/index.php/<token>` bi na PHP sajtu vratila 200 → lažni `infra.soft404` (high)."""
    with IndexPhpSajt() as site:
        snapshot = scan(site)
        ocekivano = probe_urls(site.base_url, site.base_url)

    assert snapshot.home.final_url.endswith("/index.php")
    assert [p.url for p in snapshot.soft404.probes] == ocekivano
    assert run_level(1, snapshot)["infra.soft404"].status == "ok"


class IstekaoSertifikat(Fetcher):
    """Bez pravog TLS servera: provera sertifikata pada, dohvat bez provere uspeva."""

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        if verify:
            return Outcome(url=url, error_kind="tls", error_detail="certificate has expired")
        if url.endswith("/"):
            return Outcome(url=url, status=200, final_url=url, redirect_chain=[url], body=html("Početna"))
        return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")


def test_tls_greska_ostaje_u_dokazu_i_kad_ponovni_dohvat_uspe():
    """Istekao sertifikat je najjači nalaz za prodaju — bez razloga je samo „nepoznata"."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with IstekaoSertifikat(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain="istekao.test"))

    snapshot = asyncio.run(run())
    assert snapshot.entry.status == 200
    assert snapshot.entry.tls.valid is False
    assert snapshot.entry.tls.error == "certificate has expired"
    nalaz = run_level(1, snapshot)["infra.tls.invalid"]
    assert nalaz.status == "finding"
    assert "certificate has expired" in render(nalaz.findings[0]).tech


class YoastSajt(FakeSite):
    """WordPress + Yoast: indeks sa devet mapa, svaka sa po nekoliko stranica.

    Snimljeno na prodavnica.example (9 mapa) i b2b-firma.example (6): čitanje svih mapa
    potroši budžet od 16 zahteva pre nego što sonde za lažni 404 dođu na red.
    """

    MAPE = 9

    def route(self, path: str) -> Response:
        base = self.base_url
        if path == "/robots.txt":
            return Response(f"User-agent: *\nSitemap: {base}/sitemap_index.xml\n".encode())
        if path == "/sitemap_index.xml":
            mape = "".join(f"<sitemap><loc>{base}/mapa-{i}.xml</loc></sitemap>" for i in range(self.MAPE))
            return Response(f"<sitemapindex>{mape}</sitemapindex>".encode())
        if path.startswith("/mapa-"):
            i = path.removeprefix("/mapa-").removesuffix(".xml")
            urls = "".join(f"<url><loc>{base}/grupa-{i}/strana-{j}</loc></url>" for j in range(3))
            return Response(f"<urlset>{urls}</urlset>".encode())
        if path.startswith("/grupa-"):
            return Response(html(path))
        return super().route(path)


def test_velika_mapa_sajta_ne_pojede_sonde_za_lazni_404():
    with YoastSajt() as site:
        snapshot = scan(site)

    assert snapshot.sitemap.nested_count == YoastSajt.MAPE
    assert len(snapshot.soft404.probes) == 2, "sonde su ostale bez budžeta"
    assert run_level(1, snapshot)["infra.soft404"].status == "ok"
    assert len(snapshot.pages) >= 6, "uzorak mora i dalje da bude upotrebljiv"
    assert not snapshot.budget.exhausted, snapshot.budget.aborted_reason


# --------------------------------------------------------------------------- #
# BUG-004: prekinuto TLS rukovanje nije nevalidan sertifikat
# --------------------------------------------------------------------------- #
def test_prekinuto_rukovanje_se_ne_klasifikuje_kao_sertifikat():
    import ssl

    try:
        try:
            raise ssl.SSLEOFError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred")
        except ssl.SSLEOFError as cause:
            raise httpx.ConnectError("greška", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "tls_handshake"


class PrekinutoRukovanje(Fetcher):
    """Snimljeno: server prekida rukovanje sa Python klijentom, a preko http-a radi."""

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        if url.startswith("https://"):
            return Outcome(
                url=url, error_kind="tls_handshake", error_detail="[SSL: UNEXPECTED_EOF_WHILE_READING]"
            )
        if url.endswith("/"):
            return Outcome(url=url, status=200, final_url=url, redirect_chain=[url], body=html("Početna"))
        return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")


def test_prekinuto_rukovanje_pada_na_http_a_sertifikat_ostaje_neproveren():
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with PrekinutoRukovanje(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain="rukovanje.test"))

    snapshot = asyncio.run(run())
    assert snapshot.entry.status == 200, "sajt koji radi preko http-a mora biti skeniran"
    assert snapshot.entry.requested_url == "http://rukovanje.test/"
    tls = run_level(1, snapshot)["infra.tls.invalid"]
    assert tls.status == "unknown", "sertifikat nije ni proveren — ni nalaz ni `ok`"


# --------------------------------------------------------------------------- #
# BUG-003 kroz ceo lanac: sajt iza zaštite od botova
# --------------------------------------------------------------------------- #
IZAZOV = (
    b"<!DOCTYPE html><html lang='en'><head><title>Checking your browser before accessing. "
    b"Just a moment...</title></head><body></body></html>"
)


class BlokiranSajt(FakeSite):
    """Svaki zahtev dobija 403 i stranu sa izazovom, kao dva sajta iz prolaza nad 100 domena."""

    def route(self, path: str) -> Response:
        return Response(IZAZOV, status=403)


def test_blokiran_sajt_nema_nijedan_nalaz():
    with BlokiranSajt() as site:
        snapshot = scan(site)
    nalazi = {cid for cid, r in run_level(1, snapshot).items() if r.status == "finding"}
    assert nalazi == set(), f"ne znamo ništa o sajtu, a prijavljeno je: {sorted(nalazi)}"


# --------------------------------------------------------------------------- #
# Prelazi stanja ulaznog zahteva: https → (sertifikat → ponovo bez provere) |
# (rukovanje, veza, istek → http) | (DNS → kraj). Za svaki prelaz: koji zahtevi su
# poslati, šta je u snapshotu i šta kaže provera sertifikata.
# --------------------------------------------------------------------------- #
OK = "ok"
ISHODI = {
    OK: None,
    "sertifikat": ("tls", "certificate has expired"),
    "rukovanje": ("tls_handshake", "UNEXPECTED_EOF_WHILE_READING"),
    "veza": ("connection", "ConnectError: odbijeno"),
    "istek": ("connect_timeout", "ConnectTimeout"),
    "dns": ("dns_nxdomain", "Name or service not known"),
}


class TabelaIshoda(Fetcher):
    """Odgovara prema tabeli: (šema, sa proverom sertifikata) → ishod."""

    def __init__(self, cfg, tabela):
        super().__init__(cfg)
        self.tabela = tabela
        self.poslato: list[tuple[str, bool]] = []

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        sema = url.split("://")[0]
        self.poslato.append((sema, verify))
        if not url.endswith("/") or url.count("/") > 3:
            return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")
        greska = ISHODI[self.tabela.get((sema, verify), "veza")]
        if greska:
            return Outcome(url=url, error_kind=greska[0], error_detail=greska[1])
        return Outcome(url=url, status=200, final_url=url, redirect_chain=[url], body=html("Početna"))


@pytest.mark.parametrize(
    "tabela, ulaz, sertifikat, prvi_zahtevi",
    [
        pytest.param({("https", True): OK}, "https", "ok", [("https", True)], id="st-https-uspeo"),
        pytest.param(
            {("https", True): "sertifikat", ("https", False): OK},
            "https", "finding", [("https", True), ("https", False)], id="st-sertifikat-pa-bez-provere",
        ),
        pytest.param(
            {("https", True): "sertifikat", ("https", False): "veza"},
            None, "finding", [("https", True), ("https", False)], id="st-sertifikat-pa-nista",
        ),
        pytest.param(
            {("https", True): "rukovanje", ("http", True): OK},
            "http", "unknown", [("https", True), ("http", True)], id="st-rukovanje-pa-http",
        ),
        pytest.param(
            {("https", True): "veza", ("http", True): OK},
            "http", "unknown", [("https", True), ("https", True), ("http", True)], id="st-veza-pa-http",
        ),
        pytest.param(
            {("https", True): "istek", ("http", True): "istek"},
            None, "unknown", [("https", True), ("https", True), ("http", True), ("http", True)],
            id="st-istek-pa-istek",
        ),
        pytest.param({("https", True): "dns"}, None, "unknown", [("https", True)], id="st-dns-kraj"),
    ],
)
def test_prelazi_stanja_ulaznog_zahteva(monkeypatch, tabela, ulaz, sertifikat, prvi_zahtevi):
    # bez pauze pred ponovni pokušaj
    monkeypatch.setattr("sitetriage.fetch.http.random.uniform", lambda *_: 0)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    fetcher = TabelaIshoda(cfg, tabela)

    async def run():
        async with fetcher:
            return await fetch_site(fetcher, DomainInput(domain="stanja.test"))

    snapshot = asyncio.run(run())
    assert fetcher.poslato[: len(prvi_zahtevi)] == prvi_zahtevi
    if ulaz is None:
        assert snapshot.entry.status is None
    else:
        assert snapshot.entry.status == 200 and snapshot.entry.requested_url.startswith(f"{ulaz}://")
    rezultati = run_level(1, snapshot)
    assert rezultati["infra.tls.invalid"].status == sertifikat
    if tabela.get(("https", True)) == "dns":
        assert len(fetcher.poslato) == 1, "posle DNS greške nema drugih zahteva"
        # Tek drugi pokušaj, koji vodi `scan_domains`, dokazuje da sajt ne radi (Z-20).
        assert rezultati["infra.unreachable"].status == "unknown"


# --------------------------------------------------------------------------- #
# Rupe iz merenja pokrivenosti
# --------------------------------------------------------------------------- #
def test_crawl_delay_iz_robots_a_se_postuje():
    """§8.3: `Crawl-delay: 1` — između dva zahteva ka sajtu bar sekunda."""
    import time

    trenuci: list[float] = []

    class Beleznica(FakeSite):
        def route(self, path: str) -> Response:
            trenuci.append(time.monotonic())
            if path == "/robots.txt":
                return Response(b"User-agent: *\nCrawl-delay: 1\n", headers={"content-type": "text/plain"})
            return super().route(path)

    with Beleznica() as site:
        scan(site, **{"http.max_requests_per_domain": 5})
    posle_robots = trenuci[1:]
    razmaci = [b - a for a, b in zip(posle_robots, posle_robots[1:], strict=False)]
    assert razmaci and min(razmaci) >= 0.9, f"razmaci: {[round(r, 2) for r in razmaci]}"


def test_pokvarena_mapa_u_indeksu_pada_na_interne_linkove():
    with FakeSite(extra={"/sitemap-1.xml": Response(b"nema", status=404)}) as site:
        snapshot = scan(site)
    assert snapshot.sitemap.status == 200, "indeks postoji"
    assert snapshot.sample_source == "links"
    assert any(p.url.endswith("/usluge") for p in snapshot.pages)


def test_izuzetak_u_domenu_daje_red_a_ne_pad(monkeypatch):
    """U2: izuzetak iz sklapanja snapshota ostaje u tom domenu."""
    import sitetriage.fetch.http as http

    async def puca(_fetcher, _target):
        raise RuntimeError("neočekivano")

    monkeypatch.setattr(http, "fetch_site", puca)
    snapshots = asyncio.run(scan_domains([DomainInput(domain="puca.test")], load_config()))
    assert len(snapshots) == 1
    assert snapshots[0].errors and snapshots[0].errors[0].kind == "RuntimeError"


def test_klijent_bez_provere_sertifikata_se_pravi_jednom():
    async def run():
        async with Fetcher(load_config()) as fetcher:
            prvi = fetcher._pick_client(verify=False)
            return prvi, fetcher._pick_client(verify=False), fetcher._pick_client(verify=True)

    prvi, drugi, sa_proverom = asyncio.run(run())
    assert prvi is drugi and prvi is not sa_proverom


@pytest.mark.parametrize(
    "exc, expected",
    [
        pytest.param(httpx.WriteTimeout("x", request=None), "timeout", id="ke-ostali-istek"),
        pytest.param(httpx.PoolTimeout("x", request=None), "timeout", id="ke-pool-istek"),
    ],
)
def test_klasifikacija_ostalih_isteka(exc, expected):
    assert _classify(exc)[0] == expected
