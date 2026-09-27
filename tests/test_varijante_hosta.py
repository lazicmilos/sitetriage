"""Z-26: isti sajt na četiri adrese (http/https × www/bez www).

Lažni sajt je tabela: poreklo → šta vraća početna. Ostale putanje (robots, mape, sonde) vraćaju 404.
"""

from __future__ import annotations

import asyncio

import pytest
from factories import clean_site, run_level
from localserver import html

from skener.config import load_config
from skener.fetch.http import Fetcher, Outcome, fetch_site
from skener.models import DomainInput, HostVariant

DOMEN = "primer.rs"
BEZ, SA = f"https://{DOMEN}", f"https://www.{DOMEN}"
HTTP_BEZ, HTTP_SA = f"http://{DOMEN}", f"http://www.{DOMEN}"
GRESKE = {
    "veza": ("no_connection", "odbijeno"),
    "dns": ("dns_nxdomain", "Name or service not known"),
    "sertifikat": ("tls", "certificate has expired"),
}
MANJKAVA = "infra.https.redirect.missing"
DUPLIKAT = "infra.host.duplicate"


class Sajt(Fetcher):
    """`ponasanje[poreklo]`: "200", poreklo na koje preusmerava, ili greška iz `GRESKE`.

    Poreklo kog nema u tabeli nema DNS zapis. Sertifikat sa greškom prolazi kad se ne proverava.
    `posluzeno` su adrese koje su vratile stranu, a preusmerenje na `stop_at` se ne prati.
    """

    def __init__(self, cfg: dict, ponasanje: dict[str, str], canonical: dict[str, str] | None = None) -> None:
        super().__init__(cfg)
        self.ponasanje = ponasanje
        self.canonical = canonical or {}
        self.poslato: list[str] = []
        self.posluzeno: list[str] = []

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        self.poslato.append(url)
        lanac = [url]
        while True:
            sema, _, ostatak = url.partition("://")
            poreklo = f"{sema}://{ostatak.split('/')[0]}"
            ishod = self.ponasanje.get(poreklo, "dns")
            if ishod == "sertifikat" and not verify:
                ishod = "200"
            if ishod in GRESKE:
                return Outcome(url=lanac[0], error_kind=GRESKE[ishod][0], error_detail=GRESKE[ishod][1])
            if ishod == "200":
                break
            url = ishod + url.removeprefix(poreklo)
            lanac.append(url)
            if url == stop_at:
                return Outcome(url=lanac[0], status=301, final_url=url, redirect_chain=lanac)
        if url != f"{poreklo}/":
            return Outcome(url=lanac[0], status=404, final_url=url, redirect_chain=lanac, body=b"")
        self.posluzeno.append(url)
        canonical = self.canonical.get(poreklo)
        glava = f'<link rel="canonical" href="{canonical}">' if canonical else ""
        return Outcome(
            url=lanac[0], status=200, final_url=url, redirect_chain=lanac, body=html("Početna", head=glava)
        )


def skeniraj(monkeypatch, ponasanje: dict[str, str], *, canonical=None, budzet: int | None = None):
    monkeypatch.setattr("skener.fetch.http.random.uniform", lambda *_: 0)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    if budzet is not None:
        cfg["http"]["max_requests_per_domain"] = budzet
    fetcher = Sajt(cfg, ponasanje, canonical)

    async def run():
        async with fetcher:
            return await fetch_site(fetcher, DomainInput(domain=DOMEN))

    return asyncio.run(run()), fetcher


def sajt(https: bool, preusmerava: bool, www: bool) -> dict[str, str]:
    ponasanje = {BEZ: "200" if https else "veza", HTTP_BEZ: BEZ if preusmerava else "200"}
    if www:
        ponasanje |= {SA: "200" if https else "veza", HTTP_SA: SA if preusmerava else "200"}
    return ponasanje


def _tab(https, preusmerava, www, manjkava, duplikat):
    ime = "-".join(
        [
            "tab",
            "https-radi" if https else "https-ne-radi",
            "http-preusmerava" if preusmerava else "http-ne-preusmerava",
            "www-postoji" if www else "www-ne-postoji",
        ]
    )
    return pytest.param(sajt(https, preusmerava, www), manjkava, duplikat, id=ime)


@pytest.mark.parametrize(
    "ponasanje, manjkava, duplikat",
    [
        _tab(True, True, False, "ok", "ok"),
        _tab(True, True, True, "ok", "finding"),
        _tab(True, False, False, "finding", "ok"),
        _tab(True, False, True, "finding", "finding"),
        # http preusmerava na https koji ne radi: sajt se ne otvara, pa nema ni tvrdnje.
        _tab(False, True, False, "unknown", "unknown"),
        _tab(False, True, True, "unknown", "unknown"),
        # Samo http: nema https-a na koji bi se preusmeravalo.
        _tab(False, False, False, "not_applicable", "ok"),
        _tab(False, False, True, "not_applicable", "finding"),
    ],
)
def test_cetiri_varijante(monkeypatch, ponasanje, manjkava, duplikat):
    snapshot, _ = skeniraj(monkeypatch, ponasanje)
    rezultati = run_level(1, snapshot)
    assert (rezultati[MANJKAVA].status, rezultati[DUPLIKAT].status) == (manjkava, duplikat)


def test_varijante_su_u_snimku_sa_lancem(monkeypatch):
    """Tri preostale varijante konačnog porekla, svaka sa statusom, konačnom adresom i lancem."""
    snapshot, _ = skeniraj(monkeypatch, sajt(True, True, True))
    varijante = {v.url: v for v in snapshot.host_variants}
    assert set(varijante) == {f"{SA}/", f"{HTTP_BEZ}/", f"{HTTP_SA}/"}
    assert varijante[f"{HTTP_SA}/"].redirect_chain == [f"{HTTP_SA}/", f"{SA}/"]
    assert varijante[f"{HTTP_SA}/"].status == 200


def test_varijanta_koja_vodi_na_pocetnu_je_ne_trazi_ponovo(monkeypatch):
    """Početna se preuzima jednom; varijanta koja na nju vodi dobija njen status i canonical."""
    snapshot, fetcher = skeniraj(monkeypatch, sajt(True, True, False), canonical={BEZ: f"{BEZ}/"})
    assert fetcher.posluzeno.count(f"{BEZ}/") == 1
    [http] = [v for v in snapshot.host_variants if v.url == f"{HTTP_BEZ}/"]
    assert (http.status, http.canonical, http.redirect_chain) == (200, f"{BEZ}/", [f"{HTTP_BEZ}/", f"{BEZ}/"])


def test_varijante_idu_pre_mape_sajta_u_budzetu(monkeypatch):
    """Početna 1 + robots 1 + varijante 3: budžet od pet zahteva ne stiže do mape sajta."""
    snapshot, fetcher = skeniraj(monkeypatch, sajt(True, True, False), budzet=5)
    assert fetcher.poslato[:2] == [f"{BEZ}/", f"{BEZ}/robots.txt"]
    assert sorted(fetcher.poslato[2:]) == sorted(v.url for v in snapshot.host_variants)
    assert len(snapshot.host_variants) == 3
    assert all(v.error_kind != "budget" for v in snapshot.host_variants)
    assert snapshot.sitemap.status is None


@pytest.mark.parametrize(
    "ponasanje, manjkava, duplikat",
    [
        pytest.param(
            {BEZ: "200", HTTP_BEZ: BEZ, SA: "sertifikat", HTTP_SA: SA},
            "ok",
            "unknown",
            id="www-sa-losim-sertifikatom",
        ),
        pytest.param(
            {BEZ: "sertifikat", HTTP_BEZ: "200"}, "unknown", "ok", id="los-sertifikat-na-konacnom-hostu"
        ),
    ],
)
def test_varijanta_sa_tls_greskom_je_unknown(monkeypatch, ponasanje, manjkava, duplikat):
    snapshot, _ = skeniraj(monkeypatch, ponasanje)
    rezultati = run_level(1, snapshot)
    assert (rezultati[MANJKAVA].status, rezultati[DUPLIKAT].status) == (manjkava, duplikat)
    if SA in ponasanje:
        [losa] = [v for v in snapshot.host_variants if v.url == f"{SA}/"]
        assert losa.error_kind == "tls" and "expired" in losa.error_detail


@pytest.mark.parametrize("canonical, ozbiljnost", [(f"{BEZ}/", "low"), (None, "medium")])
def test_canonical_na_svim_varijantama_spusta_na_low(canonical, ozbiljnost):
    site = clean_site(domain=DOMEN)
    site.home.canonical_normalized = canonical
    www = HostVariant(url=f"{HTTP_SA}/", status=200, final_url=f"{HTTP_SA}/", canonical=canonical)
    site.host_variants = [www]
    rezultat = run_level(1, site)[DUPLIKAT]
    assert rezultat.status == "finding" and rezultat.findings[0].severity == ozbiljnost


def test_bez_snimljenih_varijanti_je_unknown():
    site = clean_site()
    site.host_variants = None
    rezultati = run_level(1, site)
    assert rezultati[MANJKAVA].status == rezultati[DUPLIKAT].status == "unknown"
