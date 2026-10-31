"""Kalibracioni testovi nad pravim sajtovima (§12.1).

Isključeni po defaultu: `pytest -m live`. Traže mrežu i listu domena, a padaju kad
nekom sajtu istekne sertifikat ili kad ga vlasnik popravi — nijedno nije greška u
alatu, pa nemaju šta da traže u CI-ju.

Repozitorijum ne imenuje nijedan pravi sajt. Listu daješ ti, kroz promenljivu
okruženja `SKENER_LIVE_CSV` koja pokazuje na CSV u formatu `domains.example.csv`:

    SKENER_LIVE_CSV=moji-domeni.csv pytest -m live

Opciona kolona `ocekivano` navodi `check_id`-eve razdvojene razmakom koje alat mora
da nađe na nivou 1; vrednost `cist` označava kontrolni čist sajt (U4 iz §1.2). Bez
promenljive se testovi preskaču.

Ovo je jedini test koji proverava da su pravi sajtovi u stanju koje očekuješ.
Fixture-i to ne rade: oni su ručno napisani, nad izmišljenim domenima (vidi
`make_fixtures.py`).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from skener.checks import registry
from skener.config import load_config
from skener.inputs import read_domain_list, read_excel_csv
from skener.models import DomainInput
from skener.score import analyze

pytestmark = pytest.mark.live

CIST = "cist"


def _lista() -> tuple[list[DomainInput], dict[str, set[str]]]:
    """Domeni i očekivani nalazi iz `SKENER_LIVE_CSV`; prazno kad promenljiva nije zadata."""
    putanja = os.environ.get("SKENER_LIVE_CSV")
    if not putanja:
        return [], {}
    data = Path(putanja).read_bytes()
    domeni, _ = read_domain_list(data, putanja)
    ocekivano = {
        (row.get("domain") or "").strip(): set((row.get("ocekivano") or "").split())
        for _, row in read_excel_csv(data, putanja).rows
    }
    return domeni, {d.domain: ocekivano.get(d.domain, set()) for d in domeni}


DOMENI, OCEKIVANO = _lista()


@pytest.fixture(scope="module")
def prolaz():
    """Jedan pravi prolaz nivoa 1 nad listom iz `SKENER_LIVE_CSV`."""
    if not DOMENI:
        pytest.skip("SKENER_LIVE_CSV nije zadat: nema liste pravih domena")
    from skener.fetch.http import scan_domains

    config = load_config()
    registry.load_all()
    sites = asyncio.run(scan_domains(DOMENI, config))
    return config, {site.domain: site for site in sites}


def _izvestaj(domain, prolaz):
    config, sites = prolaz
    site = sites[domain]
    if site.home is None or site.home.status != 200:
        pytest.skip(f"{domain} nije dostupan: {site.entry.error_kind if site.entry else 'nepoznato'}")
    return analyze(site, config)


def test_nijedan_domen_ne_ruši_prolaz(prolaz):
    """U2 iz §1.2: koliko domena uđe, toliko redova izađe."""
    _config, sites = prolaz
    assert set(sites) == set(OCEKIVANO)


@pytest.mark.parametrize("domain", sorted(d for d, o in OCEKIVANO.items() if o - {CIST}))
def test_nalazi_nivoa_1_nad_pravim_sajtom(domain, prolaz):
    found = {f.check_id for f in _izvestaj(domain, prolaz).findings}
    expected_level1 = {
        check_id
        for check_id in OCEKIVANO[domain] - {CIST}
        if registry.REGISTRY[check_id].level == 1
    }
    missing = expected_level1 - found
    assert not missing, (
        f"{domain}: lista očekuje {sorted(missing)}, a alat ih ne nalazi. "
        f"Ili je sajt popravljen, ili prag treba kalibrisati. Pronađeno: {sorted(found)}"
    )


@pytest.mark.parametrize("domain", sorted(d for d, o in OCEKIVANO.items() if CIST in o))
def test_kontrolni_sajt_ostaje_cist(domain, prolaz):
    """U4 iz §1.2 — ograničenje, ne poželjna osobina."""
    report = _izvestaj(domain, prolaz)
    assert len(report.findings) <= 2, f"lažni pozitivi: {[f.check_id for f in report.findings]}"


def test_prolaz_je_unutar_budzeta(prolaz):
    """§4.2: najviše 19 zahteva po domenu (Z-26)."""
    _config, sites = prolaz
    for domain, site in sites.items():
        assert site.budget.requests_made <= 19, f"{domain}: {site.budget.requests_made} zahteva"
