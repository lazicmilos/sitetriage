"""Scoring, ranking and escalation.

The score pairs of the fixture sites are not an illustration but a claim about the whole
chain: severity → points → industry multiplier → total → ranking key. If any link moves,
these tests fail.
"""

from __future__ import annotations

import pytest
from factories import CONFIG, clean_site, run_level

from sitetriage.models import CheckResult, Finding, Reason
from sitetriage.score import (
    build_report,
    escalation_reasons,
    level1_score,
    rank,
    select_for_level2,
    weigh,
)


def finding(check_id: str, category: str, severity: str, level: int = 1) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status="finding",
        findings=[
            Finding(
                domain="d.rs",
                check_id=check_id,
                level=level,
                category=category,
                severity=severity,
                evidence={"count": 1},
            )
        ],
    )


# Findings of the reference set (tests/test_reference_set.py), written out in a checkable form.
REFERENCE_SET = {
    "restoran-centar.example": (
        "restaurant",
        [
            finding("perf.page.weight", "perf", "critical", level=2),
            finding("seo.canonical.missing", "seo", "high"),
        ],
    ),
    "restoran-ugao.example": (
        "restaurant",
        [
            finding("seo.canonical.missing", "seo", "high"),
            finding("seo.description.missing", "seo", "medium"),
            finding("social.og.title.missing", "social", "high"),
            finding("social.og.description.missing", "social", "medium"),
        ],
    ),
    "institucija.example": (
        "institution",
        [
            finding("seo.canonical.duplicate", "seo", "critical"),
            finding("infra.soft404", "infra", "high"),
            finding("seo.h1.missing", "seo", "high", level=2),
        ],
    ),
    "hotel-planina.example": (
        "hotel",
        [
            finding("seo.canonical.missing", "seo", "high"),
            finding("social.og.title.missing", "social", "high"),
            finding("infra.sitemap.missing", "infra", "medium"),
            finding("infra.robots.missing", "infra", "low"),
            finding("i18n.lang.invalid", "i18n", "medium"),
            finding("seo.h1.missing", "seo", "high", level=2),
        ],
    ),
}


def report_for(domain: str):
    industry, results = REFERENCE_SET[domain]
    site = clean_site(domain=domain, industry=industry)
    return build_report(site, results, CONFIG)


# --------------------------------------------------------------------------- #
# Industry multipliers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "category, severity, industry, expected",
    [
        ("perf", "critical", "restaurant", 60.0),  # 40 × 1.5
        ("seo", "high", "restaurant", 24.0),  # 20 × 1.2
        ("social", "high", "restaurant", 30.0),  # 20 × 1.5
        ("social", "high", "b2b", 14.0),  # 20 × 0.7: b2b links are not shared in messages
        ("a11y", "high", "healthcare", 30.0),  # 20 × 1.5
        ("infra", "medium", "hotel", 8.0),  # infra is 1.0 everywhere
        ("i18n", "medium", "hotel", 10.4),  # 8 × 1.3
        ("qa", "low", "hotel", 2.1),  # 3 × 0.7: a weak sales signal
    ],
)
def test_multipliers(category, severity, industry, expected):
    found = finding("x", category, severity).findings[0]
    assert weigh(found, industry, CONFIG) == expected


# --------------------------------------------------------------------------- #
# Exact score pairs from the specification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "domain, max_weight, total",
    [
        ("restoran-centar.example", 60.0, 84.0),
        ("restoran-ugao.example", 30.0, 75.6),
        ("institucija.example", 40.0, 80.0),
        ("hotel-planina.example", 30.0, 99.4),
    ],
)
def test_rank_key_from_specification(domain, max_weight, total):
    report = report_for(domain)
    assert report.rank_key == pytest.approx((max_weight, total))


def test_one_critical_beats_four_medium_findings():
    """First row: restoran-centar above restoran-ugao although it has fewer findings."""
    restaurant, corner = report_for("restoran-centar.example"), report_for("restoran-ugao.example")
    assert len(restaurant.findings) < len(corner.findings)
    assert rank([corner, restaurant])[0].domain == "restoran-centar.example"


def test_worst_finding_beats_larger_total():
    """Second row: the whole point of the rule.

    The hotel has a larger total (99.4 against 80), but the institution has a more
    expensive single problem. If the implementation reverses this, the bug is in
    `rank_key`, not in the thresholds.
    """
    institution, hotel = report_for("institucija.example"), report_for("hotel-planina.example")
    assert hotel.total_score > institution.total_score
    order = [r.domain for r in rank([hotel, institution])]
    assert order == ["institucija.example", "hotel-planina.example"]


def test_ranking_assigns_positions():
    """The hotel and restoran-ugao are tied at 30; the total breaks the tie (99.4 > 75.6)."""
    order = rank([report_for(d) for d in REFERENCE_SET])
    assert [r.rank for r in order] == [1, 2, 3, 4]
    assert [r.domain for r in order] == [
        "restoran-centar.example",  # (60; 84)
        "institucija.example",  # (40; 80)
        "hotel-planina.example",  # (30; 99.4)
        "restoran-ugao.example",  # (30; 75.6)
    ]


def test_findings_are_sorted_by_weight_and_three_fit_in_the_email():
    report = report_for("hotel-planina.example")
    weights = [f.weight for f in report.findings]
    assert weights == sorted(weights, reverse=True)
    assert len(report.top_findings) == 3
    assert report.top_findings[0].weight == 30.0


def test_severity_does_not_change_after_multiplication():
    """The multiplier changes the number of points, not the severity."""
    report = report_for("restoran-centar.example")
    worst = report.findings[0]
    assert worst.severity == "critical" and worst.weight == 60.0


def test_empty_report_has_zero_not_a_crash():
    report = build_report(clean_site(), [], CONFIG)
    assert report.rank_key == (0.0, 0.0)
    assert report.findings == [] and report.status == "scanned"


def test_status_partial_when_there_is_unknown():
    site = clean_site()
    results = [CheckResult(check_id="x", status="unknown", reason=Reason("load_not_measured"))]
    assert build_report(site, results, CONFIG).status == "partial"


def test_status_failed_when_home_page_was_not_fetched():
    site = clean_site()
    site.pages.clear()
    assert build_report(site, [], CONFIG).status == "failed"


# --------------------------------------------------------------------------- #
# Escalation policy
# --------------------------------------------------------------------------- #
def test_clean_fast_site_does_not_go_to_level2():
    site = clean_site()
    assert escalation_reasons(site, run_level(1, site).values(), CONFIG) == []


def test_empty_raw_html_sends_to_level2():
    """This is the institution: the content is rendered by JS, level 1 sees nothing."""
    site = clean_site()
    site.home.text_length = 120
    site.home.h1_count_raw = 0
    reasons = escalation_reasons(site, run_level(1, site).values(), CONFIG)
    assert len(reasons) >= 2
    assert any(r.code == "no_h1_raw" for r in reasons)


def test_empty_raw_html_is_a_signal_not_a_finding():
    """If you report it as a finding, you told the client there is no h1 although there is one."""
    site = clean_site()
    site.home.text_length = 120
    site.home.h1_count_raw = 0
    found = {cid for cid, r in run_level(1, site).items() if r.status == "finding"}
    assert "seo.h1.missing" not in found
    assert not any(cid.startswith("seo.h1") for cid in found)


def test_medium_severity_finding_sends_to_level2():
    site = clean_site()
    site.home.meta_description = None  # medium
    reasons = escalation_reasons(site, run_level(1, site).values(), CONFIG)
    assert any(r.code == "medium_finding" for r in reasons)


def test_slow_home_page_sends_to_level2():
    """The last condition of the policy, the only non-trivial case.

    `b2b-firma.example` is "clean SEO, slow page": no level 1 findings, it has content in
    the raw HTML, its HTML is not large. By the first conditions it would never reach
    level 2 and the tool would call it clean.
    """
    site = clean_site()
    results = run_level(1, site)
    assert not any(r.status == "finding" for r in results.values()), "the site is clean on level 1"

    site.entry.elapsed_ms = 2400
    reasons = escalation_reasons(site, results.values(), CONFIG)
    assert len(reasons) == 1
    assert reasons[0].code == "slow_entry" and reasons[0].evidence["ms"] == 2400


def test_large_html_sends_to_level2():
    site = clean_site()
    site.home.html_bytes = 400_000
    assert any(r.code == "html_large" for r in escalation_reasons(site, [], CONFIG))


def test_domain_without_home_page_does_not_go_to_level2():
    site = clean_site()
    site.pages.clear()
    assert escalation_reasons(site, [], CONFIG) == []


def test_upper_limit_picks_highest_scores():
    """Without a cap on level 2 the two-level architecture has no purpose.

    Among candidates that already have a strong level 1 finding, the highest scores go first.
    """
    candidates = []
    for i in range(5):
        site = clean_site(domain=f"d{i}.rs", industry="restaurant")
        severity = "critical" if i == 4 else "medium"
        candidates.append((site, [finding("perf.page.weight", "perf", severity)]))

    config = {**CONFIG, "escalation": {**CONFIG["escalation"], "max_level2": 2}}
    chosen = select_for_level2(candidates, config)
    assert len(chosen) == 2
    assert chosen[0].domain == "d4.rs", "the domain with the highest level 1 score goes first"


def test_level1_score_does_not_count_level2_findings():
    site = clean_site(industry="restaurant")
    results = [finding("seo.canonical.missing", "seo", "high")]
    assert level1_score(site, results, CONFIG) == 24.0


def test_limit_does_not_cut_a_site_whose_only_chance_is_level2():
    """BUG-005: selection by level 1 score always cut sites with a score of 0.

    Such a site is a candidate only because of signals seen in the browser (a slow
    home page, no h1 in the raw HTML). If it does not go to level 2, the report shows
    it as "0 findings", although it was never measured. Sites that already have a level 1
    finding at least have a reason for an email.
    """
    candidates = [
        (clean_site(domain=f"nalaz{i}.rs"), [finding("seo.description.missing", "seo", "medium")])
        for i in range(3)
    ]
    slow = clean_site(domain="spor.rs")
    slow.entry.elapsed_ms = 2400
    candidates.append((slow, []))

    config = {**CONFIG, "escalation": {**CONFIG["escalation"], "max_level2": 2}}
    chosen = [site.domain for site in select_for_level2(candidates, config)]
    assert "spor.rs" in chosen, f"chosen: {chosen}"
    assert len(chosen) == 2
