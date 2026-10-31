"""The reference set: eight typical sites and the `check_id`s each must produce, in executable form.

For each domain the **expected set must be a subset of what is found**, and for
`klinika.example` the found set must also be small.

A fair warning: the snapshots in `tests/fixtures/` are **hand-written**, over made-up
domains under `.example` (see `tests/make_fixtures.py`). So these tests claim that the
chain of checks works correctly over the described state, not that any real site is in
that state. That is what `pytest -m live` is for (see `tests/test_live.py`).
"""

from __future__ import annotations

import datetime as dt
import warnings
from pathlib import Path

import pytest

from sitetriage import store
from sitetriage.checks import registry
from sitetriage.config import load_config
from sitetriage.messages import LANGS, render
from sitetriage.models import SEVERITY_ORDER
from sitetriage.score import analyze, escalation_reasons, rank

FIXTURES = Path(__file__).parent / "fixtures"
MAX_AGE_DAYS = 90

# (industry, required check_ids), copied from the specification's table.
EXPECTED = {
    "institucija.example": ("institution", {"seo.canonical.duplicate", "infra.soft404", "seo.h1.missing"}),
    "hotel-planina.example": (
        "hotel",
        {
            "seo.canonical.missing",
            "social.og.title.missing",
            "infra.sitemap.missing",
            "infra.robots.missing",
            "i18n.lang.invalid",
            "seo.h1.missing",
        },
    ),
    "restoran-centar.example": ("restaurant", {"seo.canonical.missing", "perf.page.weight"}),
    "restoran-ugao.example": (
        "restaurant",
        {
            "seo.canonical.missing",
            "seo.description.missing",
            "social.og.title.missing",
            "social.og.description.missing",
        },
    ),
    "prodavnica.example": (
        "ecommerce",
        {"seo.h1.missing", "perf.page.weight", "perf.request.count"},
    ),
    "ordinacija.example": ("healthcare", {"i18n.lang.mismatch", "a11y.img.alt.missing"}),
    "b2b-firma.example": ("b2b", set()),
    "klinika.example": ("healthcare", set()),
}


def spec_config() -> dict:
    """The weight thresholds from the specification, not the calibrated ones.

    This set checks that the chain snapshot → checks → points → ranking works over the
    state the specification describes. Calibrating thresholds on real sites has its own
    boundary value tests; if the calibrated thresholds applied here, every calibration
    would "break" the specification.
    """
    config = load_config()
    config["thresholds"]["perf"]["page_weight_mb"] = {"medium": 1.5, "high": 3.0, "critical": 8.0}
    return config


@pytest.fixture(scope="module")
def reports():
    registry.load_all()
    config = spec_config()
    reports = {}
    for site, browser in store.read_all(FIXTURES):
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        reasons = escalation_reasons(site, registry.run(1, site, ctx), config)
        reports[site.domain] = analyze(site, config, browser=browser, escalation=reasons)
    return reports


def ids(report) -> set[str]:
    return {f.check_id for f in report.findings}


def test_all_domains_from_the_table_exist(reports):
    assert set(reports) == set(EXPECTED), "the fixtures and the specification's table disagree"


@pytest.mark.parametrize("domain", sorted(EXPECTED))
def test_expected_findings_are_a_subset_of_found(domain, reports):
    industry, expected = EXPECTED[domain]
    report = reports[domain]
    assert report.industry == industry
    assert expected <= ids(report), f"missing: {sorted(expected - ids(report))}"


@pytest.mark.parametrize("domain", sorted(EXPECTED))
def test_every_finding_has_evidence_and_sentence(domain, reports):
    for finding in reports[domain].findings:
        assert finding.evidence, f"{finding.check_id}: a finding without evidence"
        assert finding.weight > 0, f"{finding.check_id}: a finding without points"
        for lang in LANGS:
            assert "{" not in render(finding, lang).client, "the sentence was not filled with values"


# --------------------------------------------------------------------------- #
# Extra conditions from the "Additional" column
# --------------------------------------------------------------------------- #
def test_institution_goes_to_level2_and_has_no_i18n_finding(reports):
    """`lang=sr` is correct: a tool that reports anything here lies to the client."""
    report = reports["institucija.example"]
    assert report.level2_ran, "the institution's content is rendered by JS, it must go to level 2"
    assert report.escalation_reasons
    assert not any(c.startswith("i18n.") for c in ids(report))


def test_hotel_planina_lands_in_invalid_not_mismatch(reports):
    found = ids(reports["hotel-planina.example"])
    assert "i18n.lang.invalid" in found
    assert "i18n.lang.mismatch" not in found, "lang=zxx is not a wrong language but no language"


def test_restoran_centar_measures_over_14_mb_and_gives_critical(reports):
    report = reports["restoran-centar.example"]
    weight = next(f for f in report.findings if f.check_id == "perf.page.weight")
    assert weight.severity == "critical"
    assert weight.evidence["bytes"] > 14_000_000
    assert weight.evidence["mb"] > 14
    # Measured from network events, not the Performance API (ADR-016).
    assert weight.evidence["bytes"] != 2048


def test_prodavnica_has_about_175_requests(reports):
    report = reports["prodavnica.example"]
    requests = next(f for f in report.findings if f.check_id == "perf.request.count")
    assert requests.evidence["requests"] >= 150 and requests.severity == "high"
    weight = next(f for f in report.findings if f.check_id == "perf.page.weight")
    assert SEVERITY_ORDER[weight.severity] >= SEVERITY_ORDER["medium"]


def test_ordinacija_evidence_tells_alt_attribute_states_apart(reports):
    """The evidence must say 28/30 and tell "no attribute" apart from `alt=""`."""
    report = reports["ordinacija.example"]
    alt = next(f for f in report.findings if f.check_id == "a11y.img.alt.missing")
    assert alt.evidence["without_alt"] == 28
    assert alt.evidence["total"] == 30
    assert alt.evidence["empty_alt"] == 1
    assert alt.severity == "high", "a share > 0.8 with ≥ 15 images becomes high"


def test_b2b_firma_has_no_seo_finding_and_still_reaches_level2(reports):
    """The most valuable test after the clinic.

    A site without level 1 findings must reach level 2 through the slow home page
    condition of the escalation policy; otherwise the tool would call it clean.
    """
    report = reports["b2b-firma.example"]
    seo = {c for c in ids(report) if c.startswith("seo.")}
    assert seo == set(), f"false positives in the SEO group: {sorted(seo)}"
    assert any(c.startswith("perf.") for c in ids(report))
    assert report.level2_ran
    assert any(reason.code == "slow_entry" for reason in report.escalation_reasons), (
        f"it had to reach level 2 because of the slow response, but it got there because of: "
        f"{report.escalation_reasons}"
    )


def test_klinika_is_clean(reports):
    """A deliberately clean control site gets no findings: the most important criterion, and the easiest
    one to lose sight of."""
    report = reports["klinika.example"]
    assert len(report.findings) <= 2, f"false positives: {sorted(ids(report))}"
    too_high = [f.check_id for f in report.findings if SEVERITY_ORDER[f.severity] > SEVERITY_ORDER["medium"]]
    assert too_high == [], f"a clean site must not have a finding above medium: {too_high}"


def test_klinika_is_at_the_bottom_of_the_ranking(reports):
    order = rank(list(reports.values()))
    assert order[-1].domain == "klinika.example"
    assert order[0].domain == "restoran-centar.example"


def test_recheck_through_pipeline_gives_the_same_ranking(reports):
    """`reports` takes the old path from `cmd_recheck`. The pipeline must not change anything."""
    from sitetriage import pipeline
    from sitetriage.models import to_jsonable

    old = rank(list(reports.values()))
    new = pipeline.recheck(FIXTURES, spec_config()).ranked
    assert [to_jsonable(r) for r in new] == [to_jsonable(r) for r in old]


# --------------------------------------------------------------------------- #
# Fixtures go stale (tests/fixtures/README.md)
# --------------------------------------------------------------------------- #
def test_fixture_age_warns_instead_of_failing():
    """When a site fixes its canonical, the test still passes over the old snapshot."""
    today = dt.datetime.now(dt.UTC)
    stale = []
    for site, _ in store.read_all(FIXTURES):
        recorded = dt.datetime.strptime(site.fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.UTC
        )
        if (today - recorded).days > MAX_AGE_DAYS:
            stale.append(f"{site.domain} ({(today - recorded).days} days)")
    if stale:
        warnings.warn(
            "Fixtures are older than 90 days; refresh them with `sitetriage record` and check the git diff: "
            + ", ".join(stale),
            stacklevel=1,
        )
