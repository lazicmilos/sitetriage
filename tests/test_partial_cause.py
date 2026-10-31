"""The cause of `partial` (ADR-015). Budget and `unknown` are two exit criteria, so they count separately.

The budget share is measured among working domains, and `unknown` per check, among the domains the
check ran on: without `failed`, `unreachable` and `excluded`, and for level 2 only where level 2 ran.
"""

from __future__ import annotations

import jsonschema
from factories import clean_browser, clean_site
from test_json import SEMA

from sitetriage import pipeline, store
from sitetriage.config import load_config
from sitetriage.models import Entry, to_jsonable
from sitetriage.report import html_out
from sitetriage.score import analyze, partial_shares


def _site(domain: str, *, budget: bool = False, unknown: bool = False):
    site = clean_site(domain=domain)
    site.budget.exhausted = budget
    if unknown:
        site.robots.status = 403  # this does not show whether robots.txt exists
    return site


def _sites():
    return [
        _site("cist.rs"),
        _site("budzet.rs", budget=True),
        _site("nepoznato.rs", unknown=True),
        _site("oba.rs", budget=True, unknown=True),
    ]


def _reports():
    config = load_config()
    return {s.domain: analyze(s, config) for s in _sites()}


def test_partial_by_budget_and_by_unknown_count_separately(tmp_path):
    reports = _reports()
    causes = {domain: r.partial_causes for domain, r in reports.items()}
    assert causes == {
        "cist.rs": [],
        "budzet.rs": ["budget"],
        "nepoznato.rs": ["unknown"],
        "oba.rs": ["budget", "unknown"],
    }
    budget, per_check = partial_shares(list(reports.values()))
    assert budget == 0.5
    assert per_check["infra.robots.missing"] == 0.5 and per_check["seo.title.missing"] == 0.0

    for site in _sites():
        store.write_site(tmp_path, site)
    result = pipeline.recheck(tmp_path, load_config())
    assert result.summary["partial_budget"] == 2 and result.summary["partial_unknown"] == 2
    assert result.budget_share == 0.5 and result.unknown_share["infra.robots.missing"] == 0.5
    jsonschema.validate(to_jsonable(result), SEMA)


def test_unknown_share_does_not_count_unreachable_domains():
    config = load_config()
    unreachable = clean_site(domain="ugasen.rs", pages=[])
    unreachable.entry = Entry("https://ugasen.rs/", error_kind="dns_nxdomain")
    unreachable.entry_attempts = ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]
    not_scanned = clean_site(domain="zatvoren.rs", pages=[])
    not_scanned.entry.status = 403
    reports = [
        analyze(_site("nepoznato.rs", unknown=True), config),
        analyze(_site("cist.rs"), config, browser=clean_browser(domain="cist.rs")),
        analyze(unreachable, config),
        analyze(not_scanned, config),
    ]
    assert [r.status for r in reports[2:]] == ["unreachable", "failed"]
    budget, per_check = partial_shares(reports)
    assert budget == 0.0
    assert per_check["infra.robots.missing"] == 0.5, "only two domains are working"
    # Level 2 ran on only one domain: the denominator is 1, not 2.
    assert per_check["perf.page.weight"] == 0.0


def test_light_level2_makes_no_partial_and_is_not_in_the_time_denominator():
    """BUG-020: light level 2 deliberately does not measure time. On list B, 29 sites were `partial` only
    because of that (owner, 5 Oct: "not applicable"). The time denominator is the sites measured under the
    profile."""
    config = load_config()
    light = clean_browser(domain="lagan.rs", light=True, network_profile=None, link_mbps=None)
    slow = clean_browser(domain="pun.rs", link_mbps=5.0)  # full level 2 on a slow link: time is unknown
    reports = [
        analyze(_site("pun.rs"), config, browser=slow),
        analyze(_site("lagan.rs"), config, browser=light),
    ]
    light_report = reports[1]
    assert light_report.status == "scanned" and light_report.partial_causes == []
    load_time = [n for n in light_report.not_applicable if n.check_id == "perf.load.time"]
    assert load_time, "the site card says the time was not measured"
    _, per_check = partial_shares(reports)
    assert per_check["perf.load.time"] == 1.0, "the light site is not in the denominator"
    assert per_check["perf.page.weight"] == 0.0


def test_level2_check_without_any_level2_domain_has_no_share():
    _, per_check = partial_shares([analyze(_site("cist.rs"), load_config())])
    assert "perf.page.weight" not in per_check and "seo.title.missing" in per_check


def test_empty_run_has_no_division_by_zero():
    assert partial_shares([]) == (0.0, {})


def test_html_shows_both_shares_per_language():
    reports = list(_reports().values())[:3]  # one in three for the budget, one in three for unknown
    sr = html_out.render(reports, load_config())
    en = html_out.render(reports, load_config(), lang="en")
    assert "Potrošen budžet: 33,3 % domena koji rade" in sr
    assert "<td>infra.robots.missing</td><td class=\"num\">33,3 %</td>" in sr
    assert "Budget spent: 33.3 % of working domains" in en
