"""Kalibracioni testovi nad pravim sajtovima (§12.1).

Isključeni po defaultu: `pytest -m live`. Traže mrežu i padaju kad nekom od osam
sajtova istekne sertifikat ili kad ga vlasnik popravi — nijedno nije greška u
alatu, pa nemaju šta da traže u CI-ju.

Ovo je i jedini test koji zaista proverava da su domeni iz §12.4 u opisanom
stanju. Fixture-i to ne rade: oni su ručno napisani (vidi `make_fixtures.py`).
"""

from __future__ import annotations

import asyncio

import pytest
from test_ispitni_skup import OCEKIVANO

from skener.checks import registry
from skener.config import load_config
from skener.models import DomainInput
from skener.score import analyze, escalation_reasons

pytestmark = pytest.mark.live

# Nalazi iz §12.4 koje je vlasnik sajta u međuvremenu popravio. Svaki red je
# proveren ručno nad snimkom — vidi docs/kalibracija.md. Fixture-i i dalje
# opisuju stanje iz specifikacije, jer proveravaju lanac, ne sajt.
POPRAVLJENO = {
    "institucija.example": {"seo.canonical.duplicate", "infra.soft404"},  # 2026-09-24
}


@pytest.fixture(scope="module")
def prolaz():
    """Jedan pravi prolaz nivoa 1 nad ispitnim skupom."""
    from skener.fetch.http import scan_domains

    config = load_config()
    registry.load_all()
    targets = [DomainInput(domain=d, industry=i) for d, (i, _) in OCEKIVANO.items()]
    sites = asyncio.run(scan_domains(targets, config))
    return config, {site.domain: site for site in sites}


def test_nijedan_domen_ne_ruši_prolaz(prolaz):
    """U2 iz §1.2: koliko domena uđe, toliko redova izađe."""
    _config, sites = prolaz
    assert set(sites) == set(OCEKIVANO)


@pytest.mark.parametrize("domain", sorted(OCEKIVANO))
def test_nalazi_nivoa_1_nad_pravim_sajtom(domain, prolaz):
    config, sites = prolaz
    site = sites[domain]
    if site.home is None or site.home.status != 200:
        pytest.skip(f"{domain} nije dostupan: {site.entry.error_kind if site.entry else 'nepoznato'}")

    report = analyze(site, config)
    found = {f.check_id for f in report.findings}
    expected_level1 = {
        check_id
        for check_id in OCEKIVANO[domain][1]
        if registry.REGISTRY[check_id].level == 1
    } - POPRAVLJENO.get(domain, set())
    missing = expected_level1 - found
    assert not missing, (
        f"{domain}: specifikacija očekuje {sorted(missing)}, a alat ih ne nalazi. "
        f"Ili je sajt popravljen, ili prag treba kalibrisati. Pronađeno: {sorted(found)}"
    )


def test_klinika_ostaje_cista_i_na_pravom_sajtu(prolaz):
    """U4 iz §1.2 — ograničenje, ne poželjna osobina."""
    config, sites = prolaz
    site = sites["klinika.example"]
    if site.home is None or site.home.status != 200:
        pytest.skip("klinika.example nije dostupna")
    report = analyze(site, config)
    assert len(report.findings) <= 2, f"lažni pozitivi: {[f.check_id for f in report.findings]}"


def test_b2b_firma_stize_na_nivo_2_bez_nalaza_nivoa_1(prolaz):
    config, sites = prolaz
    site = sites["b2b-firma.example"]
    if site.home is None or site.home.status != 200:
        pytest.skip("b2b-firma.example nije dostupan")
    ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
    assert escalation_reasons(site, registry.run(1, site, ctx), config), (
        "sajt čiji je jedini problem na nivou 2 mora da stigne do nivoa 2"
    )


def test_prolaz_je_unutar_budzeta(prolaz):
    """§4.2: najviše 16 zahteva po domenu."""
    _config, sites = prolaz
    for domain, site in sites.items():
        assert site.budget.requests_made <= 16, f"{domain}: {site.budget.requests_made} zahteva"
