"""Ceo prolaz bez komandne linije: isto zovu CLI i web worker."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from localserver import FakeSite, Response, html

from skener import pipeline
from skener.config import load_config
from skener.inputs import InputError
from skener.models import DomainInput

FIXTURES = Path(__file__).parent / "fixtures"


def brza_konfiguracija() -> dict:
    config = load_config()
    config["http"]["delay_ms"] = [0, 0]
    config["http"]["second_attempt_after_s"] = 0
    return config


# --------------------------------------------------------------------------- #
# Bez mreže
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("targets", "level", "greska"),
    [
        pytest.param([], "auto", InputError, id="nv-prazna-lista"),
        pytest.param([DomainInput("primer.rs")], "3", ValueError, id="nv-nepoznat-nivo"),
    ],
)
def test_scan_odbija_neispravan_ulaz(targets, level, greska):
    with pytest.raises(greska):
        asyncio.run(pipeline.scan(targets, load_config(), level=level))


def test_recheck_bez_snapshota_je_greska_ulaza(tmp_path):
    with pytest.raises(InputError, match="nijedan snapshot"):
        pipeline.recheck(tmp_path, load_config())


def test_rezultat_nosi_zbir_po_statusu_i_vreme():
    rezultat = pipeline.recheck(FIXTURES, load_config())
    statusi = ("scanned", "partial", "failed", "unreachable", "excluded")
    assert set(rezultat.summary) == {*statusi, "partial_budget", "partial_unknown"}
    svi = rezultat.ranked + rezultat.unreachable + rezultat.not_scanned
    assert sum(rezultat.summary[s] for s in statusi) == len(svi), "recheck nema izuzetih"
    assert rezultat.started_at.endswith("Z") and rezultat.finished_at >= rezultat.started_at
    assert rezultat.duration_s["total"] >= 0


def test_greska_u_on_event_ne_obara_prolaz(caplog):
    """Traka napretka koja pukne ne sme da izgubi domen čiji je snapshot već na disku."""

    def puca(_event):
        raise RuntimeError("traka napretka")

    rezultat = pipeline.recheck(FIXTURES, load_config(), on_event=puca)
    assert len(rezultat.ranked) == sum(1 for p in FIXTURES.iterdir() if p.is_dir())
    assert "on_event pukao" in caplog.text


# --------------------------------------------------------------------------- #
# Pravi Chromium protiv lokalnog servera
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def dva_prolaza():
    """Dva prolaza, jedan za drugim, u istoj petlji — kao u workeru koji dugo živi."""
    config = brza_konfiguracija()
    dogadjaji: list[list] = [[], []]

    async def glavni(targets):
        return [
            await pipeline.scan(targets, config, level="2", on_event=dogadjaji[i].append) for i in range(2)
        ]

    with FakeSite() as prvi, FakeSite() as drugi:
        targets = [DomainInput(prvi.base_url), DomainInput(drugi.base_url)]
        rezultati = asyncio.run(glavni(targets))
    return targets, rezultati, dogadjaji


@pytest.mark.browser
def test_dva_prolaza_u_istoj_petlji(dva_prolaza):
    targets, rezultati, _ = dva_prolaza
    for rezultat in rezultati:
        assert sorted(r.domain for r in rezultat.ranked) == sorted(t.domain for t in targets)
        assert all(r.level2_ran for r in rezultat.ranked)
        assert set(rezultat.duration_s) == {"level1", "level2", "total"}
        assert rezultat.environment["chromium"], "verzija Chromium-a kojim je meren nivo 2"


@pytest.mark.browser
def test_dogadjaj_za_svaki_zavrsen_domen(dva_prolaza):
    targets, _, dogadjaji = dva_prolaza
    for dogadjaj in dogadjaji:
        assert [e.phase for e in dogadjaj] == ["level1"] * 4 + ["level2"] * 4, "nivo 1 pa nivo 2"
        for faza in ("level1", "level2"):
            svi = [e for e in dogadjaj if e.phase == faza]
            assert svi[0].kind == "phase_started" and svi[-1].kind == "phase_finished"
            domeni = [e for e in svi if e.kind == "domain_finished"]
            assert sorted(e.domain for e in domeni) == sorted(t.domain for t in targets)
            assert [e.done for e in domeni] == [1, 2] and all(e.total == 2 for e in svi)
            assert all(e.status for e in domeni)


@pytest.mark.browser
def test_otkazan_prolaz_zatvara_browser_i_cuva_zavrsene_snapshote(tmp_path, monkeypatch):
    from playwright.async_api import BrowserType

    pokrenuti = []
    pravi_launch = BrowserType.launch

    async def launch(self, **kwargs):
        browser = await pravi_launch(self, **kwargs)
        pokrenuti.append(browser)
        return browser

    monkeypatch.setattr(BrowserType, "launch", launch)

    async def glavni(targets):
        prolaz = asyncio.current_task()

        def otkazi_kad_prvi_zavrsi_nivo_2(event):
            if event.phase == "level2" and event.kind == "domain_finished":
                prolaz.cancel()

        await pipeline.scan(
            targets,
            brza_konfiguracija(),
            level="2",
            snapshot_dir=tmp_path,
            on_event=otkazi_kad_prvi_zavrsi_nivo_2,
        )

    # Spori sajt posle učitavanja traži resurs čije telo stiže tek za 20 s, pa njegovo
    # merenje još traje kad brzi završi i prolaz se otkaže.
    spora = html("Spora", body="<script>fetch('/kasno')</script>")
    with FakeSite() as brz, FakeSite(
        extra={"/": Response(spora), "/kasno": Response(b"x" * 1000, stall=20)}
    ) as spor:
        targets = [DomainInput(brz.base_url), DomainInput(spor.base_url)]
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(glavni(targets))

    assert pokrenuti and not any(b.is_connected() for b in pokrenuti), "browser mora biti zatvoren"
    assert len(list(tmp_path.glob("*/site.json"))) == 2, "nivo 1 je završen za oba domena"
    assert len(list(tmp_path.glob("*/browser.json"))) == 1, "nivo 2 je završen samo za brzi"


# --------------------------------------------------------------------------- #
# Izuzeti domeni (opt-out)
# --------------------------------------------------------------------------- #
def test_izuzet_domen_ne_dobija_nijedan_zahtev(monkeypatch):
    """Lokalni serveri dele host 127.0.0.1, pa je drugi domen u listi ime bez DNS zapisa."""
    import socket

    from skener.fetch import http

    async def nema_zapisa(host, port):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(http, "_razresi", nema_zapisa)
    with FakeSite() as izuzet:
        targets = [DomainInput(izuzet.base_url), DomainInput("drugi.test")]
        rezultat = asyncio.run(
            pipeline.scan(targets, brza_konfiguracija(), level="1", excluded=["127.0.0.1"])
        )
    assert izuzet.requests == [], "izuzet domen ne sme da dobije nijedan zahtev"
    svi = rezultat.ranked + rezultat.unreachable + rezultat.not_scanned
    assert [r.domain for r in svi] == ["drugi.test"], "u izveštaju nema imena izuzetog"
    assert rezultat.summary["excluded"] == 1
