"""Zaštita od SSRF-a (ADR-006): skener ne otvara privatne adrese, ni posle DNS-a ni posle
preusmerenja. Lokalni server je na 127.0.0.1, pa je dozvoljen samo kad test to traži.
"""

from __future__ import annotations

import asyncio
import socket

import pytest
from localserver import FakeSite, Response, html

from skener.config import load_config
from skener.fetch import http
from skener.fetch.http import Fetcher, fetch_site
from skener.models import DomainInput
from skener.score import analyze


# --------------------------------------------------------------------------- #
# Nivo 1 protiv lokalnog servera
# --------------------------------------------------------------------------- #
def _skeniraj(domen: str, config: dict | None = None):
    cfg = config or load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=domen))

    return asyncio.run(run())


def test_lokalni_server_bez_dozvole_ne_dobija_nijedan_zahtev():
    with FakeSite(dozvoljen=False) as site:
        snapshot = _skeniraj(site.base_url)
    assert site.requests == []
    assert snapshot.entry.error_kind == "blocked"


def test_izricita_dozvola_otvara_tacno_taj_host_i_port():
    with FakeSite(dozvoljen=False) as site:
        cfg = load_config()
        host, port = site.address
        cfg["net"]["allowed_private"] = [f"{host}:{port}"]
        snapshot = _skeniraj(site.base_url, cfg)
    assert snapshot.entry.status == 200 and site.requests


def test_preusmerenje_na_privatnu_adresu_se_odbija():
    """Dozvoljen server preusmerava na drugi port; provera je pri otvaranju svake veze."""
    with FakeSite(dozvoljen=False) as cilj:
        preusmerenje = Response(b"", status=302, headers={"location": f"{cilj.base_url}/"})
        with FakeSite(extra={"/": preusmerenje}) as site:
            snapshot = _skeniraj(site.base_url)
    assert cilj.requests == [], "cilj preusmerenja ne sme da dobije nijedan zahtev"
    assert snapshot.entry.error_kind == "blocked"
    assert "127.0.0.1 → 127.0.0.1" in snapshot.entry.error_detail


def test_ime_koje_se_razresava_u_privatnu_adresu_se_odbija(monkeypatch):
    razreseno = []

    async def lazni_dns(host, port):
        razreseno.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(http, "_razresi", lazni_dns)
    snapshot = _skeniraj("privatno.test")
    assert razreseno and set(razreseno) == {"privatno.test"}
    assert snapshot.entry.error_kind == "blocked"
    assert snapshot.entry.error_detail == "adresa nije javna: privatno.test → 10.0.0.5"
    assert snapshot.pages == [], "posle blokade nema ni robots.txt ni mape sajta"


def test_odbijena_veza_na_dozvoljenoj_adresi_nije_blokada():
    """Dozvoljena adresa na kojoj niko ne sluša je obična mrežna greška, ne zaštita."""
    cfg = load_config()
    cfg["net"]["allowed_private"] = ["127.0.0.1:1"]
    snapshot = _skeniraj("http://127.0.0.1:1", cfg)
    assert snapshot.entry.error_kind == "no_connection"


def test_zastita_ne_nestaje_tiho_kad_se_httpx_promeni(monkeypatch):
    """Backend se postavlja kroz interno polje httpx-a; bez njega alat odbija da radi."""
    import types

    import httpx

    class BezBackenda(httpx.AsyncHTTPTransport):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._pool = types.SimpleNamespace()

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", BezBackenda)
    with pytest.raises(RuntimeError, match="SSRF"):
        Fetcher(load_config())._make_client(verify=True)


def test_ime_bez_dns_zapisa_ostaje_dns_greska(monkeypatch):
    async def nema_zapisa(host, port):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(http, "_razresi", nema_zapisa)
    assert _skeniraj("nepostoji.test").entry.error_kind == "dns_nxdomain"


def test_blokiran_domen_nije_unreachable():
    """Sajt možda radi — samo ga mi namerno nismo otvorili. To je `failed`, ne „ne radi"."""
    with FakeSite(dozvoljen=False) as site:
        snapshot = _skeniraj(site.base_url)
    izvestaj = analyze(snapshot, load_config())
    assert izvestaj.status == "failed"
    assert snapshot.entry.error_kind == "blocked"


def test_ulaz_sa_ip_adresom_ne_salje_nijedan_zahtev():
    with FakeSite(dozvoljen=False) as site:
        _, port = site.address
        snapshot = _skeniraj(f"127.0.0.1:{port}")
    assert site.requests == []
    assert snapshot.entry.error_kind == "blocked" and "portom" in snapshot.entry.error_detail


# --------------------------------------------------------------------------- #
# Nivo 2: log kaže zašto je zahtev odbijen. Chromium za oba slučaja javlja isto,
# ERR_BLOCKED_BY_CLIENT, a neuspeo DNS nije privatna adresa.
# --------------------------------------------------------------------------- #
class LaznaRuta:
    def __init__(self, url: str) -> None:
        self.request = type("Zahtev", (), {"url": url})()
        self.ishod: str | None = None

    async def continue_(self) -> None:
        self.ishod = "continue"

    async def abort(self, kod: str) -> None:
        self.ishod = kod


@pytest.mark.parametrize(
    "razresi, razlog",
    [
        pytest.param(socket.gaierror(socket.EAI_AGAIN, "privremeno"), "DNS nije razrešio ime", id="ke-dns"),
        pytest.param(
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))],
            "adresa nije javna: 10.0.0.5",
            id="ke-privatna",
        ),
    ],
)
def test_nivo_2_upisuje_zasto_odbija_zahtev(monkeypatch, caplog, razresi, razlog):
    from skener.fetch.browser import _cuvar

    def lazni_dns(*_args, **_kwargs):
        if isinstance(razresi, Exception):
            raise razresi
        return razresi

    monkeypatch.setattr(socket, "getaddrinfo", lazni_dns)
    ruta = LaznaRuta("https://primer.rs/")
    caplog.set_level("INFO", logger="skener")
    asyncio.run(_cuvar(frozenset(), RuntimeError, "primer.rs")(ruta))
    assert ruta.ishod == "blockedbyclient"
    [zapis] = [r for r in caplog.records if "odbija" in r.getMessage()]
    assert razlog in zapis.getMessage() and "primer.rs:443" in zapis.getMessage()
    assert zapis.domain == "primer.rs"


# --------------------------------------------------------------------------- #
# Nivo 2: `route` proverava svaki zahtev browsera
# --------------------------------------------------------------------------- #
def _nivo2(site: FakeSite):
    from skener.fetch.browser import capture_all
    from skener.models import Entry, PageSnapshot, SiteSnapshot

    snimak = SiteSnapshot(
        domain=site.base_url,
        pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        entry=Entry(requested_url=site.base_url + "/", final_url=site.base_url + "/", status=200),
    )
    return asyncio.run(capture_all([snimak], load_config()))[site.base_url]


@pytest.mark.browser
def test_browser_ne_ucitava_resurs_sa_privatne_adrese():
    with FakeSite(dozvoljen=False) as privatni:
        strana = html("Strana", body=f"<img src='{privatni.base_url}/slika.png'>")
        with FakeSite(extra={"/": Response(strana)}) as site:
            snimak = _nivo2(site)
    assert snimak.status == "ok", snimak.errors
    assert privatni.requests == [], "browser ne sme da dohvati resurs sa privatne adrese"


@pytest.mark.browser
def test_browser_ne_otvara_stranicu_na_privatnoj_adresi():
    with FakeSite(dozvoljen=False) as privatni:
        snimak = _nivo2(privatni)
    assert snimak.status == "failed" and snimak.errors[0].stage == "goto"
    assert privatni.requests == []


@pytest.mark.browser
@pytest.mark.xfail(
    strict=True, reason="ADR-006: Playwright `route` ne vidi cilj preusmerenja; štiti egress filter"
)
def test_browser_ne_prati_preusmerenje_na_privatnu_adresu():
    """Poznato ograničenje nivoa 2. Kad Playwright počne da vidi preusmerenja, test prolazi
    i `strict` ga obara, pa se ograničenje briše iz ADR-006."""
    with FakeSite(dozvoljen=False) as cilj:
        preusmerenje = Response(b"", status=302, headers={"location": f"{cilj.base_url}/"})
        with FakeSite(extra={"/": preusmerenje}) as site:
            _nivo2(site)
    assert cilj.requests == []
