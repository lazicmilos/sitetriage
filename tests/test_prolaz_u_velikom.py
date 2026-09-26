"""Kriterijumi uspeha U1 i U2 iz §1.2, koliko se mogu proveriti bez prave mreže.

U2 („nijedan domen ne ruši prolaz") se proverava u potpunosti: u listu se ubacuju
namerno pokvareni domeni i tvrdi se da izađe tačno onoliko redova koliko je ušlo.

U1 („200 domena za ≤ 15 minuta") se **ne** može proveriti lokalno — lokalni
server odgovara za mikrosekunde, a u pravom prolazu vreme diktiraju mrežna
latencija i pauze pristojnosti. Ono što se ovde proverava je mehanizam od kog U1
zavisi: da domeni idu paralelno, a ne jedan za drugim.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from localserver import FakeSite

from skener.config import load_config
from skener.fetch.http import scan_domains
from skener.models import DomainInput
from skener.score import analyze, rank

BROJ_SAJTOVA = 12


@pytest.fixture(scope="module")
def veliki_prolaz():
    sites = [FakeSite() for _ in range(BROJ_SAJTOVA)]
    for site in sites:
        site.__enter__()
    try:
        config = load_config()
        config["http"]["delay_ms"] = [0, 0]
        targets = [DomainInput(domain=s.base_url, industry="ostalo") for s in sites]
        # Pokvareni domeni: niko ne sluša, server odbija, server traži da se stane.
        targets += [
            DomainInput(domain="http://127.0.0.1:1"),
            DomainInput(domain="http://127.0.0.1:2"),
        ]
        config["http"]["timeout_connect_s"] = 1
        started = time.monotonic()
        snapshots = asyncio.run(scan_domains(targets, config))
        yield config, targets, snapshots, time.monotonic() - started
    finally:
        for site in sites:
            site.__exit__()


def test_u2_koliko_udje_toliko_izadje(veliki_prolaz):
    """§1.2, U2: pokvaren domen daje red u izlazu, ne izuzetak."""
    config, targets, snapshots, _elapsed = veliki_prolaz
    assert len(snapshots) == len(targets)
    assert [s.domain for s in snapshots] == [t.domain for t in targets], "redosled se ne sme pomešati"

    reports = [analyze(s, config) for s in snapshots]
    assert len(reports) == len(targets)
    # Rangiraju se samo sajtovi koji rade (Z-20); pokvareni su `failed`, ali nisu izgubljeni.
    assert [r.rank for r in rank(reports)] == list(range(1, BROJ_SAJTOVA + 1))


def test_pokvareni_domeni_su_failed_a_ne_izuzetak(veliki_prolaz):
    from skener.checks import registry

    config, _targets, snapshots, _elapsed = veliki_prolaz
    registry.load_all()
    pokvareni = [s for s in snapshots if s.domain.endswith((":1", ":2"))]
    assert len(pokvareni) == 2

    for site in pokvareni:
        report = analyze(site, config)
        assert report.status == "failed"

        # Svaka provera daje rezultat — nijedna ne nestaje i nijedna ne puca.
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        results = registry.run(1, site, ctx)
        assert len(results) == 22
        assert all(r.reason for r in results if r.status == "unknown")

        # Ono što nismo mogli da proverimo ne sme da se prijavi kao uredno.
        po_id = {r.check_id: r for r in results}
        assert po_id["infra.tls.invalid"].status == "unknown"
        assert po_id["perf.redirect.chain"].status == "unknown"
        # Jedan pokušaj bez odgovora ne dokazuje da sajt ne radi (Z-20).
        assert po_id["infra.unreachable"].status == "unknown"


def test_ispravni_domeni_prolaze_uprkos_pokvarenim(veliki_prolaz):
    _config, _targets, snapshots, _elapsed = veliki_prolaz
    ispravni = [s for s in snapshots if not s.domain.endswith((":1", ":2"))]
    assert len(ispravni) == BROJ_SAJTOVA
    assert all(s.entry.status == 200 for s in ispravni)
    assert all(len(s.pages) >= 4 for s in ispravni)


def test_domeni_idu_paralelno_a_ne_jedan_za_drugim(veliki_prolaz):
    """Mehanizam od kog U1 zavisi (§8.1).

    Serijski bi prolaz trajao bar `broj_domena × vreme_po_domenu`. Ovde se samo
    tvrdi da je ukupno vreme znatno ispod tog zbira.
    """
    _config, _targets, snapshots, elapsed = veliki_prolaz
    ukupno_zahteva = sum(s.budget.requests_made for s in snapshots)
    assert ukupno_zahteva > BROJ_SAJTOVA * 8, "svaki domen troši 10-16 zahteva (§4.2)"
    serijski = sum(s.budget.elapsed_ms for s in snapshots) / 1000
    assert elapsed < serijski * 0.6, (
        f"prolaz je trajao {elapsed:.1f} s, a zbir vremena po domenima je {serijski:.1f} s — "
        f"domeni se ne preklapaju dovoljno"
    )


def test_budzet_se_postuje_na_svakom_domenu(veliki_prolaz):
    _config, _targets, snapshots, _elapsed = veliki_prolaz
    for site in snapshots:
        assert site.budget.requests_made <= 16, f"{site.domain}: {site.budget.requests_made}"
