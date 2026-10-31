"""Success criteria U1 and U2 of the original specification, as far as they can be checked without a
real network.

U2 ("no domain crashes the run"; as many rows out as domains in) is checked in full: deliberately
broken domains are added to the list, and exactly as many rows must come out as went in.

U1 ("200 domains in ≤ 15 minutes", ADR-019) **cannot** be checked locally: the local server answers
in microseconds, and in a real run network latency and politeness delays set the time. What is
checked here is the mechanism U1 depends on: domains run in parallel, not one after another.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from localserver import FakeSite

from sitetriage.config import load_config
from sitetriage.fetch.http import scan_domains
from sitetriage.models import DomainInput
from sitetriage.score import analyze, rank

SITE_COUNT = 12


@pytest.fixture(scope="module")
def large_run():
    sites = [FakeSite() for _ in range(SITE_COUNT)]
    for site in sites:
        site.__enter__()
    try:
        config = load_config()
        config["http"]["delay_ms"] = [0, 0]
        targets = [DomainInput(domain=s.base_url, industry="other") for s in sites]
        # Broken domains: nobody listens, the server refuses, the server asks to stop.
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


def test_u2_as_many_out_as_in(large_run):
    """U2: a broken domain gives a row in the output, not an exception."""
    config, targets, snapshots, _elapsed = large_run
    assert len(snapshots) == len(targets)
    assert [s.domain for s in snapshots] == [t.domain for t in targets], "the order must not get mixed up"

    reports = [analyze(s, config) for s in snapshots]
    assert len(reports) == len(targets)
    # Only working sites are ranked (ADR-013); the broken ones are `failed`, but not lost.
    assert [r.rank for r in rank(reports)] == list(range(1, SITE_COUNT + 1))


def test_broken_domains_are_failed_not_an_exception(large_run):
    from sitetriage.checks import registry

    config, _targets, snapshots, _elapsed = large_run
    registry.load_all()
    broken = [s for s in snapshots if s.domain.endswith((":1", ":2"))]
    assert len(broken) == 2

    for site in broken:
        report = analyze(site, config)
        assert report.status == "failed"

        # Every check gives a result: none disappears and none crashes.
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        results = registry.run(1, site, ctx)
        assert len(results) == 22
        assert all(r.reason for r in results if r.status == "unknown")

        # What we could not check must not be reported as fine.
        by_id = {r.check_id: r for r in results}
        assert by_id["infra.tls.invalid"].status == "unknown"
        assert by_id["perf.redirect.chain"].status == "unknown"
        # One attempt without a response does not prove the site is unreachable (ADR-013).
        assert by_id["infra.unreachable"].status == "unknown"


def test_working_domains_pass_despite_broken_ones(large_run):
    _config, _targets, snapshots, _elapsed = large_run
    working = [s for s in snapshots if not s.domain.endswith((":1", ":2"))]
    assert len(working) == SITE_COUNT
    assert all(s.entry.status == 200 for s in working)
    assert all(len(s.pages) >= 4 for s in working)


def test_domains_run_in_parallel_not_one_after_another(large_run):
    """The mechanism U1 depends on: the global semaphore lets domains overlap.

    Run serially, the run would take at least `domain_count × time_per_domain`. Here we only
    assert that the total time is well below that sum.
    """
    _config, _targets, snapshots, elapsed = large_run
    total_requests = sum(s.budget.requests_made for s in snapshots)
    assert total_requests > SITE_COUNT * 8, "every domain spends 10-16 requests"
    serial = sum(s.budget.elapsed_ms for s in snapshots) / 1000
    assert elapsed < serial * 0.6, (
        f"the run took {elapsed:.1f} s, and the sum of per-domain times is {serial:.1f} s; "
        f"the domains do not overlap enough"
    )


def test_budget_is_respected_on_every_domain(large_run):
    _config, _targets, snapshots, _elapsed = large_run
    for site in snapshots:
        assert site.budget.requests_made <= 16, f"{site.domain}: {site.budget.requests_made}"
