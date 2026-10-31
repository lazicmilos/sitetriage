"""Boundary values and decision tables for every threshold in the README.

Every threshold gets three points: limit − 1, limit, limit + 1. That is where defects live: `>`
instead of `>=` moves a finding by one unit, and no test "from the middle" sees it.
Case id prefixes: `gv-` boundary value, `ke-` equivalence class, `tab-` decision table
column (`nv-` marks an invalid value).
"""

from __future__ import annotations

import pytest
from factories import CONFIG, clean_browser, clean_site, run_level

from sitetriage.fetch.http import DomainBudget
from sitetriage.models import CheckResult, Finding, OversizedImage, Reason, Unknown
from sitetriage.score import _status, build_report, escalation_reasons, select_for_level2


def finding(check_id: str, category: str, severity: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status="finding",
        findings=[
            Finding(
                domain="d.rs", check_id=check_id, level=1, category=category, severity=severity,
                evidence={"count": 1},
            )
        ],
    )


# --------------------------------------------------------------------------- #
# Level 1
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "html_bytes, expected",
    [
        pytest.param(51_199, "ok", id="gv-50kB-minus"),
        pytest.param(51_200, "ok", id="gv-50kB"),
        pytest.param(51_201, "finding", id="gv-50kB-plus"),
    ],
)
def test_compression_boundary(html_bytes, expected):
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = html_bytes
    assert run_level(1, site)["perf.compression.missing"].status == expected


@pytest.mark.parametrize(
    "encoding, expected",
    [
        pytest.param("gzip", "ok", id="ke-gzip"),
        pytest.param("br", "ok", id="ke-br"),
        pytest.param("zstd", "ok", id="ke-zstd"),
        pytest.param("deflate", "ok", id="ke-deflate"),
        pytest.param("GZIP", "ok", id="pg-upper-case"),
        pytest.param("identity", "finding", id="ke-uncompressed"),
        pytest.param("", "finding", id="ke-no-header"),
    ],
)
def test_compression_encoding_classes(encoding, expected):
    site = clean_site()
    site.home.headers = {"content-encoding": encoding}
    site.home.html_bytes = 80_000
    assert run_level(1, site)["perf.compression.missing"].status == expected


@pytest.mark.parametrize(
    "html_bytes, expected",
    [
        pytest.param(511_999, "ok", id="gv-500kB-minus"),
        pytest.param(512_000, "ok", id="gv-500kB"),
        pytest.param(512_001, "finding", id="gv-500kB-plus"),
    ],
)
def test_html_size_boundary(html_bytes, expected):
    site = clean_site()
    site.home.html_bytes = html_bytes
    assert run_level(1, site)["perf.html.size"].status == expected


@pytest.mark.parametrize(
    "hops, expected",
    [
        pytest.param(2, "ok", id="gv-3-minus"),
        pytest.param(3, "finding", id="gv-3"),
        pytest.param(4, "finding", id="gv-3-plus"),
    ],
)
def test_redirect_chain_boundary(hops, expected):
    site = clean_site()
    site.entry.redirect_chain = [f"https://cist.rs/korak{i}" for i in range(hops + 1)]
    assert run_level(1, site)["perf.redirect.chain"].status == expected


def _same_title(site, page_count: int, group_count: int) -> None:
    """`page_count` pages with the same title, spread over `group_count` path groups."""
    for i, page in enumerate(site.pages[:page_count]):
        page.title = "Dobrodošli"
        group = "/" if i == 0 else f"/g{min(i, group_count - 1)}"
        page.final_url = f"https://cist.rs{group}/strana{i}" if group != "/" else "https://cist.rs/"


@pytest.mark.parametrize(
    "pages, groups, expected",
    [
        pytest.param(2, 2, "ok", id="gv-pages-3-minus"),
        pytest.param(3, 3, "finding", id="gv-pages-3"),
        pytest.param(4, 3, "finding", id="gv-pages-3-plus"),
        pytest.param(4, 2, "ok", id="gv-groups-3-minus"),
        pytest.param(5, 4, "finding", id="gv-groups-3-plus"),
    ],
)
def test_title_duplicate_boundaries(pages, groups, expected):
    site = clean_site()
    _same_title(site, pages, groups)
    assert run_level(1, site)["seo.title.duplicate"].status == expected


# --- language: three thresholds (min. text, Cyrillic share, diacritic share) ---
def _text(site, text: str, lang: str = "en") -> None:
    site.home.lang = lang
    site.home.text_sample = text
    site.home.text_length = len(text)


@pytest.mark.parametrize(
    "length, expected",
    [
        pytest.param(399, "unknown", id="gv-400-minus"),
        pytest.param(400, "finding", id="gv-400"),
        pytest.param(401, "finding", id="gv-400-plus"),
    ],
)
def test_language_minimum_text(length, expected):
    site = clean_site()
    _text(site, ("č" * 5 + "a" * 95) * 5)
    site.home.text_length = length
    assert run_level(1, site)["i18n.lang.mismatch"].status == expected


@pytest.mark.parametrize(
    "cyrillic, expected",
    [
        pytest.param(29, "ok", id="gv-30pct-minus"),
        pytest.param(30, "ok", id="gv-30pct"),
        pytest.param(31, "finding", id="gv-30pct-plus"),
    ],
)
def test_language_cyrillic_share(cyrillic, expected):
    """The Cyrillic share must be > 0.30 (of all letters); the Latin letters here have no diacritics."""
    site = clean_site()
    _text(site, ("ж" * cyrillic + "a" * (100 - cyrillic)) * 5)
    assert run_level(1, site)["i18n.lang.mismatch"].status == expected


@pytest.mark.parametrize(
    "diacritics, expected",
    [
        pytest.param(4, "ok", id="gv-0.5pct-minus"),
        pytest.param(5, "ok", id="gv-0.5pct"),
        pytest.param(6, "finding", id="gv-0.5pct-plus"),
    ],
)
def test_language_diacritic_share(diacritics, expected):
    """The diacritic share must be > 0.005 of the Latin letters: 5 of 1000 is not enough."""
    site = clean_site()
    _text(site, "č" * diacritics + "a" * (1000 - diacritics))
    assert run_level(1, site)["i18n.lang.mismatch"].status == expected


@pytest.mark.parametrize(
    "lang, expected",
    [
        pytest.param("sr", "ok", id="ke-valid-2-letters"),
        pytest.param("srp", "ok", id="ke-valid-3-letters"),
        pytest.param("sr-Latn-RS", "ok", id="ke-valid-with-subtags"),
        pytest.param("s", "finding", id="gv-1-letter"),
        pytest.param("serb", "finding", id="gv-4-letters"),
        pytest.param("", "finding", id="nv-empty"),
        pytest.param("   ", "finding", id="nv-whitespace"),
        pytest.param("zxx", "finding", id="nv-zxx"),
        pytest.param("und", "finding", id="nv-und"),
        pytest.param("sr_RS", "finding", id="nv-underscore"),
    ],
)
def test_language_tag_classes(lang, expected):
    site = clean_site()
    site.home.lang = lang
    assert run_level(1, site)["i18n.lang.invalid"].status == expected


# --------------------------------------------------------------------------- #
# Level 2
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "requests, expected",
    [
        pytest.param(60, None, id="gv-60"),
        pytest.param(61, "medium", id="gv-60-plus"),
        pytest.param(90, "medium", id="gv-90"),
        pytest.param(91, "high", id="gv-90-plus"),
    ],
)
def test_request_count_boundaries(requests, expected):
    browser = clean_browser()
    browser.network.requests_at_load = requests
    result = run_level(2, browser)["perf.request.count"]
    assert (result.findings[0].severity if result.findings else None) == expected


@pytest.mark.parametrize(
    "load_ms, expected",
    [
        pytest.param(6000, None, id="gv-6s"),
        pytest.param(6001, "medium", id="gv-6s-plus"),
        pytest.param(9000, "medium", id="gv-9s"),
        pytest.param(9001, "high", id="gv-9s-plus"),
    ],
)
def test_load_time_boundaries(load_ms, expected):
    browser = clean_browser()
    browser.timing.load_ms = load_ms
    result = run_level(2, browser)["perf.load.time"]
    assert (result.findings[0].severity if result.findings else None) == expected


@pytest.mark.parametrize(
    "unmeasured, expected",
    [
        pytest.param(5, "ok", id="gv-5"),
        pytest.param(6, "unknown", id="gv-5-plus"),
    ],
)
def test_unmeasured_responses_boundary(unmeasured, expected):
    browser = clean_browser()
    browser.network.unmeasured_at_load = unmeasured
    assert run_level(2, browser)["perf.page.weight"].status == expected


@pytest.mark.parametrize(
    "h1, expected",
    [
        pytest.param(3, "ok", id="gv-3"),
        pytest.param(4, "finding", id="gv-3-plus"),
    ],
)
def test_multiple_h1_boundary(h1, expected):
    browser = clean_browser()
    browser.dom.h1_count = h1
    assert run_level(2, browser)["seo.h1.multiple"].status == expected


@pytest.mark.parametrize(
    "errors, expected",
    [
        pytest.param(3, "ok", id="gv-3"),
        pytest.param(4, "finding", id="gv-3-plus"),
    ],
)
def test_console_errors_boundary(errors, expected):
    browser = clean_browser()
    browser.console.errors = errors
    assert run_level(2, browser)["qa.console.errors"].status == expected


def _oversized(count: int, waste_kb: float) -> list[OversizedImage]:
    return [
        OversizedImage(src=f"https://cist.rs/s{i}.jpg", natural=[2000, 1000], client=[200, 100],
                       ratio=10.0, est_waste_kb=waste_kb / count)
        for i in range(count)
    ]


@pytest.mark.parametrize(
    "count, waste_kb, expected",
    [
        pytest.param(2, 100, "ok", id="gv-3-images-minus"),
        pytest.param(3, 100, "finding", id="gv-3-images"),
        pytest.param(1, 700, "ok", id="gv-700kB"),
        pytest.param(1, 701, "finding", id="gv-700kB-plus"),
    ],
)
def test_oversized_images_boundaries(count, waste_kb, expected):
    browser = clean_browser()
    browser.dom.oversized_images = _oversized(count, waste_kb)
    assert run_level(2, browser)["perf.img.oversized"].status == expected


@pytest.mark.parametrize(
    "total, without_alt, industry, expected",
    [
        pytest.param(4, 4, "other", None, id="gv-5-images-minus"),
        pytest.param(5, 5, "other", "low", id="gv-5-images"),
        pytest.param(10, 5, "other", None, id="gv-share-0.5"),
        pytest.param(10, 6, "other", "low", id="gv-share-0.5-plus"),
        pytest.param(15, 12, "other", "low", id="gv-share-0.8"),
        pytest.param(15, 13, "other", "high", id="gv-share-0.8-plus"),
        pytest.param(14, 14, "other", "low", id="gv-15-images-minus"),
        pytest.param(15, 15, "other", "high", id="gv-15-images"),
        pytest.param(10, 6, "healthcare", "medium", id="ke-healthcare"),
        pytest.param(10, 6, "institution", "medium", id="ke-institution"),
        pytest.param(10, 6, "hotel", "low", id="ke-other-industries"),
    ],
)
def test_alt_boundaries_and_industries(total, without_alt, industry, expected):
    browser = clean_browser()
    browser.dom.images_total = total
    browser.dom.images_without_alt_attr = without_alt
    browser.dom.images_empty_alt = 0
    result = run_level(2, browser, industry=industry)["a11y.img.alt.missing"]
    assert (result.findings[0].severity if result.findings else None) == expected


# --------------------------------------------------------------------------- #
# Escalation policy: six conditions joined by OR. A decision table per MC/DC
# (each condition alone changes the outcome), plus boundary values of three thresholds.
# --------------------------------------------------------------------------- #
def _break(site, condition: str) -> list:
    if condition == "empty-html":
        site.home.text_length = 799
    elif condition == "no-h1":
        site.home.h1_count_raw = 0
    elif condition == "medium-finding":
        site.home.meta_description = None
    elif condition == "large-html":
        site.home.html_bytes = 300_001
    elif condition == "uncompressed":
        site.home.headers = {}
        site.home.html_bytes = 60_000
    elif condition == "slow-home-page":
        site.entry.elapsed_ms = 1501
    return list(run_level(1, site).values())


@pytest.mark.parametrize(
    "condition, code",
    [
        pytest.param("empty-html", "raw_text_short", id="tab-empty-html"),
        pytest.param("no-h1", "no_h1_raw", id="tab-no-h1"),
        pytest.param("medium-finding", "medium_finding", id="tab-medium-finding"),
        pytest.param("large-html", "html_large", id="tab-large-html"),
        pytest.param("uncompressed", "html_uncompressed", id="tab-uncompressed"),
        pytest.param("slow-home-page", "slow_entry", id="tab-slow-home-page"),
    ],
)
def test_escalation_each_condition_alone_changes_outcome(condition, code):
    site = clean_site()
    reasons = escalation_reasons(site, _break(site, condition), CONFIG)
    assert reasons and any(r.code == code for r in reasons), reasons


def test_escalation_no_condition():
    site = clean_site()
    assert escalation_reasons(site, list(run_level(1, site).values()), CONFIG) == []


@pytest.mark.parametrize(
    "field, value, goes",
    [
        pytest.param("text_length", 799, True, id="gv-800-minus"),
        pytest.param("text_length", 800, False, id="gv-800"),
        pytest.param("html_bytes", 300_000, False, id="gv-300kB"),
        pytest.param("html_bytes", 300_001, True, id="gv-300kB-plus"),
        pytest.param("elapsed_ms", 1500, False, id="gv-1500ms"),
        pytest.param("elapsed_ms", 1501, True, id="gv-1500ms-plus"),
    ],
)
def test_escalation_boundaries(field, value, goes):
    site = clean_site()
    setattr(site.entry if field == "elapsed_ms" else site.home, field, value)
    assert bool(escalation_reasons(site, [], CONFIG)) is goes


def test_low_severity_finding_is_no_reason_to_escalate():
    """The equivalence class below the severity threshold: `low` alone does not send to level 2."""
    site = clean_site()
    assert escalation_reasons(site, [finding("infra.robots.missing", "infra", "low")], CONFIG) == []


# --------------------------------------------------------------------------- #
# Domain status: decision table (unreachable, home page, unknown, budget)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "unreachable, home, unknown, budget, expected",
    [
        pytest.param(False, False, False, False, "failed", id="tab-no-home-page"),
        pytest.param(False, False, True, True, "failed", id="tab-no-home-page-everything-else"),
        pytest.param(False, True, False, False, "scanned", id="tab-all-fine"),
        pytest.param(False, True, True, False, "partial", id="tab-unknown"),
        pytest.param(False, True, False, True, "partial", id="tab-budget"),
        pytest.param(False, True, True, True, "partial", id="tab-unknown-and-budget"),
        pytest.param(True, False, False, False, "unreachable", id="tab-unreachable"),
        pytest.param(True, False, True, True, "unreachable", id="tab-unreachable-everything-else"),
    ],
)
def test_domain_status_table(unreachable, home, unknown, budget, expected):
    site = clean_site()
    if not home:
        site.pages.clear()
    site.budget.exhausted = budget
    findings = [Finding("cist.rs", "infra.unreachable", 1, "infra", "critical")] if unreachable else []
    unknowns = [Unknown(check_id="seo.title.duplicate", reason=Reason("requires.pages"))] if unknown else []
    assert _status(site, findings, unknowns) == expected


# --------------------------------------------------------------------------- #
# Level 2 limit: boundary of the candidate count
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "candidate_count, chosen",
    [
        pytest.param(2, 2, id="gv-limit-minus"),
        pytest.param(3, 3, id="gv-limit"),
        pytest.param(4, 3, id="gv-limit-plus"),
        pytest.param(0, 0, id="ke-no-candidates"),
    ],
)
def test_level2_limit_boundaries(candidate_count, chosen):
    config = {**CONFIG, "escalation": {**CONFIG["escalation"], "max_level2": 3}}
    candidates = [
        (clean_site(domain=f"d{i}.rs"), [finding("seo.description.missing", "seo", "medium")])
        for i in range(candidate_count)
    ]
    assert len(select_for_level2(candidates, config)) == chosen


# --------------------------------------------------------------------------- #
# Per-domain budget: number of requests and time (ADR-014)
# --------------------------------------------------------------------------- #
def test_request_budget_boundary():
    budget = DomainBudget(max_requests=16, max_seconds=40)
    allowed = [budget.take() for _ in range(16)]
    assert all(allowed), "the 16th request is still within the budget"
    assert budget.take() is False, "the 17th request breaks the budget"


@pytest.mark.parametrize(
    "elapsed, allowed",
    [
        pytest.param(39.999, True, id="gv-40s-minus"),
        pytest.param(40.0, False, id="gv-40s"),
        pytest.param(40.001, False, id="gv-40s-plus"),
    ],
)
def test_time_budget_boundary(monkeypatch, elapsed, allowed):
    clock = {"now": 1000.0}
    monkeypatch.setattr("sitetriage.fetch.http.time.monotonic", lambda: clock["now"])
    budget = DomainBudget(max_requests=16, max_seconds=40)
    clock["now"] = 1000.0 + elapsed
    assert budget.take() is allowed


def test_unknown_brings_no_points_but_status_partial():
    """The `unknown` class must not turn into points, but it must show in the status."""
    site = clean_site()
    unknown = CheckResult(check_id="seo.title.duplicate", status="unknown", reason=Reason("requires.pages"))
    report = build_report(site, [unknown], CONFIG)
    assert report.findings == [] and report.total_score == 0
    assert report.status == "partial"
    assert [u.check_id for u in report.unknowns] == ["seo.title.duplicate"]
