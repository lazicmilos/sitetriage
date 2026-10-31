"""Calibration tests against real sites.

Excluded by default: `pytest -m live`. They need the network and a domain list, and they fail
when a site's certificate expires or when its owner fixes it. Neither is a bug in the tool,
so they have no place in CI.

The repository names no real site. You provide the list, through the environment variable
`SITETRIAGE_LIVE_CSV` that points to a CSV in the `domains.example.csv` format:

    SITETRIAGE_LIVE_CSV=my-domains.csv pytest -m live

The optional column `expected` lists space-separated `check_id`s the tool must find on
level 1; the value `clean` marks the control clean site (a deliberately clean site must get
no findings). Without the variable the tests are skipped. `SITETRIAGE_LIVE_PROFILE` names a
profile (ADR-023), e.g. `rs` for a list of Serbian sites that expects `i18n.lang.mismatch`.

This is the only test that checks that real sites are in the state you expect.
Fixtures do not do that: they are hand-written, over made-up domains (see
`make_fixtures.py`).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from sitetriage.checks import registry
from sitetriage.config import load_config
from sitetriage.inputs import read_domain_list, read_excel_csv
from sitetriage.models import DomainInput
from sitetriage.score import analyze

pytestmark = pytest.mark.live

# The value of the `expected` column that marks the control clean site.
CLEAN_MARKER = "clean"


def _domain_list() -> tuple[list[DomainInput], dict[str, set[str]]]:
    """Domains and expected findings from `SITETRIAGE_LIVE_CSV`; empty when the variable is not set."""
    path = os.environ.get("SITETRIAGE_LIVE_CSV")
    if not path:
        return [], {}
    data = Path(path).read_bytes()
    domains, _ = read_domain_list(data, path)
    expected = {
        (row.get("domain") or "").strip(): set((row.get("expected") or "").split())
        for _, row in read_excel_csv(data, path).rows
    }
    return domains, {d.domain: expected.get(d.domain, set()) for d in domains}


DOMAINS, EXPECTED = _domain_list()


@pytest.fixture(scope="module")
def live_run():
    """One real level 1 run over the list from `SITETRIAGE_LIVE_CSV`."""
    if not DOMAINS:
        pytest.skip("SITETRIAGE_LIVE_CSV is not set: there is no list of real domains")
    from sitetriage.fetch.http import scan_domains

    config = load_config(profile=os.environ.get("SITETRIAGE_LIVE_PROFILE") or None)
    registry.load_all()
    sites = asyncio.run(scan_domains(DOMAINS, config))
    return config, {site.domain: site for site in sites}


def _report(domain, live_run):
    config, sites = live_run
    site = sites[domain]
    if site.home is None or site.home.status != 200:
        pytest.skip(f"{domain} is not reachable: {site.entry.error_kind if site.entry else 'unknown'}")
    return analyze(site, config)


def test_no_domain_crashes_the_run(live_run):
    """As many rows come out as domains go in."""
    _config, sites = live_run
    assert set(sites) == set(EXPECTED)


@pytest.mark.parametrize("domain", sorted(d for d, o in EXPECTED.items() if o - {CLEAN_MARKER}))
def test_level1_findings_on_real_site(domain, live_run):
    found = {f.check_id for f in _report(domain, live_run).findings}
    expected_level1 = {
        check_id
        for check_id in EXPECTED[domain] - {CLEAN_MARKER}
        if registry.REGISTRY[check_id].level == 1
    }
    missing = expected_level1 - found
    assert not missing, (
        f"{domain}: the list expects {sorted(missing)}, but the tool does not find them. "
        f"Either the site was fixed, or the threshold needs calibrating. Found: {sorted(found)}"
    )


@pytest.mark.parametrize("domain", sorted(d for d, o in EXPECTED.items() if CLEAN_MARKER in o))
def test_control_site_stays_clean(domain, live_run):
    """A deliberately clean control site gets no findings: a constraint, not a nice-to-have."""
    report = _report(domain, live_run)
    assert len(report.findings) <= 2, f"false positives: {[f.check_id for f in report.findings]}"


def test_run_stays_within_budget(live_run):
    """At most 19 requests per domain (ADR-014)."""
    _config, sites = live_run
    for domain, site in sites.items():
        assert site.budget.requests_made <= 19, f"{domain}: {site.budget.requests_made} requests"
