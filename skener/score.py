"""Bodovanje, rangiranje i politika eskalacije (§6, §9). Čisto: bez I/O.

Sve troje su odluke nad već prikupljenim podacima, pa žive zajedno i testiraju se
zajedno. Eskalacija je ovde jer joj treba skor nivoa 1: kad kandidata ima više od
gornjeg limita, prolaze oni sa najvišim (§6).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from skener.config import get, multiplier
from skener.models import (
    SEVERITY_ORDER,
    BrowserSnapshot,
    CheckResult,
    DomainReport,
    Finding,
    Reason,
    SiteSnapshot,
    Unknown,
)

# Sajtovi koji rade: samo oni se rangiraju i samo oni ulaze u imenilac udela iz §7.
RADE = ("scanned", "partial")


def weigh(finding: Finding, industry: str, config: dict) -> float:
    """`weight = base_points × industry_multiplier[industry][category]` (§9.2).

    Ozbiljnost se posle množenja **ne menja** — menja se samo broj bodova (§3.5).
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
    """Udeo budžeta među domenima koji rade, i udeo `unknown`-a po proveri (Z-22, §7).

    Imenilac za proveru su domeni koji rade i na kojima je pokrenuta: nivo 2 samo gde je radio.
    `failed`, `unreachable` i izuzeti ne ulaze, jer tamo nijedna provera nije ni imala šta da vidi.
    """
    from skener.checks import registry

    registry.load_all()
    rade = [r for r in reports if r.status in RADE]
    budzet = sum("budget" in r.partial_causes for r in rade)
    po_proveri = {}
    for spec in sorted(registry.REGISTRY.values(), key=lambda s: s.check_id):
        # Provera bez ispunjenog preduslova nije ni pokrenuta, npr. vreme na laganom nivou 2 (BUG-020).
        pokrenuta = [
            r
            for r in rade
            if (spec.level == 1 or r.level2_ran)
            and not any(
                n.check_id == spec.check_id and n.reason.code.startswith("requires.")
                for n in r.not_applicable
            )
        ]
        if pokrenuta:
            nepoznato = sum(any(u.check_id == spec.check_id for u in r.unknowns) for r in pokrenuta)
            po_proveri[spec.check_id] = round(nepoznato / len(pokrenuta), 4)
    return (round(budzet / len(rade), 4) if rade else 0.0), po_proveri


def _failure(site: SiteSnapshot) -> Reason:
    """Zašto početna nije stigla, za listu „Nije skenirano"."""
    entry = site.entry
    if entry is None:
        return Reason("entry_missing")
    if entry.status is not None:
        return Reason("entry_status", {"status": entry.status})
    return Reason("entry_error", {"vrsta": entry.error_kind, "detalj": entry.error_detail or ""})


def rank(reports: Iterable[DomainReport]) -> list[DomainReport]:
    """§9.4: sajt sa jednom katastrofom je bolji lead od sajta sa deset sitnica.

    Primarni ključ je najteži pojedinačni nalaz; zbir samo razrešava izjednačenje.
    Rangiranje po zbiru bi Ariju stavilo iznad Mense, a Institucija ima najskuplji SEO
    problem koji postoji. Rangiraju se samo sajtovi koji rade (Z-20): onaj koji se ne
    otvara ide u „Ne rade", a onaj koji alat nije pregledao u „Nije skenirano".
    """
    rade = (r for r in reports if r.status in RADE)
    ordered = sorted(rade, key=lambda r: (-r.max_finding_weight, -r.total_score, r.domain))
    for position, report in enumerate(ordered, start=1):
        report.rank = position
    return ordered


# --------------------------------------------------------------------------- #
# Politika eskalacije na nivo 2 (§6)
# --------------------------------------------------------------------------- #
def escalation_reasons(site: SiteSnapshot, results: Sequence[CheckResult], config: dict) -> list[Reason]:
    """Razlozi zbog kojih domen ide na nivo 2; prazna lista znači da ne ide.

    Prazan sirovi HTML **nije nalaz**, nego signal. Ako ga prijaviš kao nalaz,
    rekao si klijentu da nema h1 iako ga ima — samo ga ti nisi video (§6).
    """
    home = site.home
    if home is None or home.status != 200:
        return []

    reasons: list[Reason] = []
    text_limit = get(config, "escalation.empty_html_text_threshold")
    if home.text_length < text_limit:
        reasons.append(Reason("raw_text_short", {"znakova": home.text_length, "prag": text_limit}))
    if home.h1_count_raw == 0:
        reasons.append(Reason("no_h1_raw"))

    findings, _ = collect(results)
    if any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"] for f in findings):
        reasons.append(Reason("medium_finding"))

    html_limit = get(config, "escalation.raw_html_bytes")
    if home.html_bytes > html_limit:
        reasons.append(Reason("html_large", {"bajtova": home.html_bytes, "prag": html_limit}))
    if any(f.check_id == "perf.compression.missing" for f in findings):
        reasons.append(Reason("html_uncompressed"))

    # Ovaj uslov zatvara rupu koju ostala četiri ostavljaju: sajt sa čistim SEO-om
    # i sporom stranicom inače nikad ne bi stigao na nivo 2 (§6, `b2b-firma.example`).
    slow = get(config, "escalation.slow_entry_ms")
    if site.entry and site.entry.elapsed_ms and site.entry.elapsed_ms > slow:
        reasons.append(Reason("slow_entry", {"ms": site.entry.elapsed_ms, "prag": slow}))
    return reasons


def level1_score(site: SiteSnapshot, results: Sequence[CheckResult], config: dict) -> float:
    findings, _ = collect(results)
    return round(sum(weigh(f, site.industry, config) for f in findings), 4)


def select_for_level2(
    candidates: Sequence[tuple[SiteSnapshot, Sequence[CheckResult]]], config: dict
) -> list[SiteSnapshot]:
    """Tvrd gornji limit (§6).

    Bez njega prvi prolaz nad 200 domena gde ih 180 ima bar jedan nalaz traje sat
    vremena i ti odustaneš od alata.
    """
    limit = get(config, "escalation.max_level2")

    def key(pair: tuple[SiteSnapshot, Sequence[CheckResult]]) -> tuple[bool, float, str]:
        site, results = pair
        findings, _ = collect(results)
        # Kandidat bez nalaza ≥ medium je kandidat samo zbog signala koje vidi browser
        # (prazan HTML, nema h1, spora početna). Nivo 2 mu je jedina šansa za pravi
        # nalaz; bez njega u izveštaju stoji kao „0 nalaza", a nije ni meren (BUG-005).
        # Zato ide prvi, pa tek onda ostali po skoru nivoa 1.
        jak = any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"] for f in findings)
        return (jak, -level1_score(site, results, config), site.domain)

    return [site for site, _ in sorted(candidates, key=key)[:limit]]


def analyze(
    site: SiteSnapshot,
    config: dict,
    *,
    browser: BrowserSnapshot | None = None,
    escalation: Sequence[Reason] = (),
) -> DomainReport:
    """Snapshoti → provere → bodovan izveštaj. Bez I/O, pa `recheck` ide bez mreže."""
    from skener.checks import registry

    registry.load_all()
    # Nivo 1 vidi i nivo 2: provera duplikata broji i veze iz renderovanog DOM-a (Z-21).
    ctx = registry.Context(domain=site.domain, industry=site.industry, config=config, browser=browser)
    results = list(registry.run(1, site, ctx))
    if browser is not None:
        results.extend(registry.run(2, browser, ctx))
    return build_report(site, results, config, browser=browser, escalation_reasons=escalation)
