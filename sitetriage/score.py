"""Scoring, ranking and the escalation policy. Pure: no I/O.

All three are decisions over data already collected, so they live together and are tested
together. Escalation is here because it needs the level 1 score: when there are more
candidates than the upper limit, the ones with the highest score go through (ADR-019).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sitetriage.config import get, multiplier
from sitetriage.models import (
    SEVERITY_ORDER,
    BrowserSnapshot,
    CheckResult,
    DomainReport,
    Finding,
    Reason,
    SiteSnapshot,
    Unknown,
)

# Working sites: only they are ranked, and only they count in the denominator of the
# exit-criteria shares (ADR-015).
WORKING_STATUSES = ("scanned", "partial")


def weigh(finding: Finding, industry: str, config: dict) -> float:
    """`weight = base_points × industry_multiplier[industry][category]`.

    The severity **does not change** after the multiplication; only the number of points does.
    """
    base = get(config, f"severity_points.{finding.severity}")
    return round(base * multiplier(config, industry, finding.category), 4)


def collect(results: Iterable[CheckResult]) -> tuple[list[Finding], list[Unknown]]:
    findings: list[Finding] = []
    unknowns: list[Unknown] = []
    for result in results:
        findings.extend(result.findings)
        if result.status == "unknown":
            unknowns.append(Unknown(check_id=result.check_id, reason=result.reason))
    return findings, unknowns


def build_report(
    site: SiteSnapshot,
    results: Sequence[CheckResult],
    config: dict,
    *,
    browser: BrowserSnapshot | None = None,
    escalation_reasons: Sequence[Reason] = (),
) -> DomainReport:
    findings, unknowns = collect(results)
    for finding in findings:
        finding.weight = weigh(finding, site.industry, config)
    findings.sort(key=lambda f: (-f.weight, f.check_id))
    status = _status(site, findings, unknowns)

    return DomainReport(
        domain=site.domain,
        industry=site.industry,
        final_url=site.entry.final_url if site.entry else None,
        status=status,
        partial_causes=_partial_causes(site, unknowns) if status == "partial" else [],
        reason=_failure(site) if status == "failed" else None,
        level2_ran=browser is not None,
        escalation_reasons=list(escalation_reasons),
        findings=findings,
        unknowns=unknowns,
        not_applicable=[Unknown(r.check_id, r.reason) for r in results if r.status == "not_applicable"],
        total_score=round(sum(f.weight for f in findings), 4),
        max_finding_weight=max((f.weight for f in findings), default=0.0),
        scanned_at=site.fetched_at,
    )


def _status(site: SiteSnapshot, findings: Sequence[Finding], unknowns: Sequence[Unknown]) -> str:
    if any(f.check_id == "infra.unreachable" for f in findings):
        return "unreachable"
    home = site.home
    if home is None or home.status != 200:
        return "failed"
    if unknowns or site.budget.exhausted:
        return "partial"
    return "scanned"


def _partial_causes(site: SiteSnapshot, unknowns: Sequence[Unknown]) -> list[str]:
    return [cause for cause, yes in (("budget", site.budget.exhausted), ("unknown", unknowns)) if yes]


def partial_shares(reports: Sequence[DomainReport]) -> tuple[float, dict[str, float]]:
    """The budget share among working domains, and the `unknown` share per check (ADR-015).

    The denominator for a check is the working domains it ran on: for level 2 only where level 2
    ran. `failed`, `unreachable` and excluded domains do not count, because no check had anything
    to see there.
    """
    from sitetriage.checks import registry

    registry.load_all()
    working = [r for r in reports if r.status in WORKING_STATUSES]
    budget = sum("budget" in r.partial_causes for r in working)
    per_check = {}
    for spec in sorted(registry.REGISTRY.values(), key=lambda s: s.check_id):
        # A check with an unmet requirement did not even run, e.g. time on light level 2 (BUG-020).
        ran_on = [
            r
            for r in working
            if (spec.level == 1 or r.level2_ran)
            and not any(
                n.check_id == spec.check_id and n.reason.code.startswith("requires.")
                for n in r.not_applicable
            )
        ]
        if ran_on:
            unknown = sum(any(u.check_id == spec.check_id for u in r.unknowns) for r in ran_on)
            per_check[spec.check_id] = round(unknown / len(ran_on), 4)
    return (round(budget / len(working), 4) if working else 0.0), per_check


def _failure(site: SiteSnapshot) -> Reason:
    """Why the home page did not arrive, for the "Not scanned" list."""
    entry = site.entry
    if entry is None:
        return Reason("entry_missing")
    if entry.status is not None:
        return Reason("entry_status", {"status": entry.status})
    return Reason("entry_error", {"kind": entry.error_kind, "detail": entry.error_detail or ""})


def rank(reports: Iterable[DomainReport]) -> list[DomainReport]:
    """A site with one disaster is a better lead than a site with ten trifles.

    The primary key is the worst single finding; the total only breaks ties.
    Ranking by the total would put the hotel above the institution, and the institution has the
    most expensive SEO problem there is. Only working sites are ranked (ADR-013): one that does
    not open goes to "Not working", and one the tool did not look at goes to "Not scanned".
    """
    working = (r for r in reports if r.status in WORKING_STATUSES)
    ordered = sorted(working, key=lambda r: (-r.max_finding_weight, -r.total_score, r.domain))
    for position, report in enumerate(ordered, start=1):
        report.rank = position
    return ordered


# --------------------------------------------------------------------------- #
# Escalation policy to level 2
# --------------------------------------------------------------------------- #
def escalation_reasons(site: SiteSnapshot, results: Sequence[CheckResult], config: dict) -> list[Reason]:
    """The reasons a domain goes to level 2; an empty list means it does not go.

    Empty raw HTML **is not a finding** but a signal. If you report it as a finding,
    you told the client there is no h1 although there is one; you just did not see it.
    """
    home = site.home
    if home is None or home.status != 200:
        return []

    reasons: list[Reason] = []
    text_limit = get(config, "escalation.empty_html_text_threshold")
    if home.text_length < text_limit:
        reasons.append(Reason("raw_text_short", {"chars": home.text_length, "threshold": text_limit}))
    if home.h1_count_raw == 0:
        reasons.append(Reason("no_h1_raw"))

    findings, _ = collect(results)
    if any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"] for f in findings):
        reasons.append(Reason("medium_finding"))

    html_limit = get(config, "escalation.raw_html_bytes")
    if home.html_bytes > html_limit:
        reasons.append(Reason("html_large", {"bytes": home.html_bytes, "threshold": html_limit}))
    if any(f.check_id == "perf.compression.missing" for f in findings):
        reasons.append(Reason("html_uncompressed"))

    # This condition closes the gap the other conditions leave: a site with clean SEO and a slow
    # page would otherwise never reach level 2 (the `b2b-firma.example` fixture).
    slow = get(config, "escalation.slow_entry_ms")
    if site.entry and site.entry.elapsed_ms and site.entry.elapsed_ms > slow:
        reasons.append(Reason("slow_entry", {"ms": site.entry.elapsed_ms, "threshold": slow}))
    return reasons


def level1_score(site: SiteSnapshot, results: Sequence[CheckResult], config: dict) -> float:
    findings, _ = collect(results)
    return round(sum(weigh(f, site.industry, config) for f in findings), 4)


def select_for_level2(
    candidates: Sequence[tuple[SiteSnapshot, Sequence[CheckResult]]], config: dict
) -> list[SiteSnapshot]:
    """A hard upper limit (ADR-019).

    Without it, the first run over 200 domains where 180 have at least one finding takes an
    hour and you give up on the tool.
    """
    limit = get(config, "escalation.max_level2")

    def key(pair: tuple[SiteSnapshot, Sequence[CheckResult]]) -> tuple[bool, float, str]:
        site, results = pair
        findings, _ = collect(results)
        # A candidate without a finding ≥ medium is a candidate only because of signals the
        # browser sees (empty HTML, no h1, slow home page). Level 2 is its only chance of a real
        # finding; without it the report shows it as "0 findings", although it was never
        # measured (BUG-005). So it goes first, and only then the others by level 1 score.
        strong = any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"] for f in findings)
        return (strong, -level1_score(site, results, config), site.domain)

    return [site for site, _ in sorted(candidates, key=key)[:limit]]


def analyze(
    site: SiteSnapshot,
    config: dict,
    *,
    browser: BrowserSnapshot | None = None,
    escalation: Sequence[Reason] = (),
) -> DomainReport:
    """Snapshots → checks → scored report. No I/O, so `recheck` runs without the network."""
    from sitetriage.checks import registry

    registry.load_all()
    # Level 1 also sees level 2: the duplicate checks also count links from the rendered DOM (ADR-015).
    ctx = registry.Context(domain=site.domain, industry=site.industry, config=config, browser=browser)
    results = list(registry.run(1, site, ctx))
    if browser is not None:
        results.extend(registry.run(2, browser, ctx))
    return build_report(site, results, config, browser=browser, escalation_reasons=escalation)
