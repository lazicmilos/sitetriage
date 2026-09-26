"""Registar provera (§2.4) i motor koji ga prolazi.

Provere se **ne pozivaju iz if-else lanca**. Svaka se registruje sa svojim
metapodacima, a motor samo prođe kroz registar — pa su lista provera, tabela u
README-u i `skener explain` jedan isti podatak, a ne tri koja se razilaze.

Pravilo koje se ne krši (§2.3): ovaj paket ne uvozi `httpx`, `playwright`, ni
`fetch.*` osim `fetch.urls`. Ako ti zatreba nešto sa mreže — fali ti polje u
snapshotu, dodaj polje.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from skener.config import get
from skener.models import BrowserSnapshot, CheckResult, Finding, Reason

CheckFn = Callable[[Any, "Context"], CheckResult]


@dataclass
class Context:
    """Sve što provera sme da zna: ko je domen, koji su pragovi i, za nivo 1, šta je video nivo 2."""

    domain: str
    industry: str
    config: dict[str, Any]
    browser: BrowserSnapshot | None = None

    def th(self, dotted: str) -> Any:
        return get(self.config, dotted)


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    level: int
    category: str
    base_severity: str
    requires: tuple[str, ...]
    description: str
    threshold: str
    fn: CheckFn


REGISTRY: dict[str, CheckSpec] = {}


def check(
    check_id: str,
    *,
    level: int,
    category: str,
    base_severity: str,
    description: str,
    threshold: str,
    requires: Iterable[str] = (),
) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        if check_id in REGISTRY:
            raise ValueError(f"duplikat check_id: {check_id}")
        spec = CheckSpec(
            check_id=check_id,
            level=level,
            category=category,
            base_severity=base_severity,
            requires=tuple(requires),
            description=description,
            threshold=threshold,
            fn=fn,
        )
        REGISTRY[check_id] = spec
        # Telo provere dohvata svoj spec preko `fn.spec` — bez traženja po registru.
        fn.spec = spec  # type: ignore[attr-defined]
        return fn

    return register


# --------------------------------------------------------------------------- #
# Konstruktori rezultata — jedini način na koji provera sme da odgovori
# --------------------------------------------------------------------------- #
def ok(spec: CheckSpec) -> CheckResult:
    return CheckResult(check_id=spec.check_id, status="ok")


def unknown(spec: CheckSpec, reason: str, **evidence: Any) -> CheckResult:
    """`unknown` bez razloga je bug (§3.4) — potpis to i ne dozvoljava.

    Razlog je kod iz kataloga (`skener.messages`) i podaci za rečenicu, kao kod nalaza.
    """
    return CheckResult(check_id=spec.check_id, status="unknown", reason=Reason(reason, evidence))


def not_applicable(spec: CheckSpec, reason: str, **evidence: Any) -> CheckResult:
    """Provera nema šta da proveri na ovom sajtu; razlog je obavezan, kao za `unknown` (Z-21)."""
    return CheckResult(check_id=spec.check_id, status="not_applicable", reason=Reason(reason, evidence))


def finding(
    spec: CheckSpec,
    ctx: Context,
    *,
    evidence: dict[str, Any],
    urls: Iterable[str] = (),
    severity: str | None = None,
    variant: str | None = None,
) -> CheckResult:
    """Nalaz nosi dokaz, a rečenicu iz njega pravi `skener.messages` pri prikazu.

    To nije stil nego tvrdnja: ako rečenica za klijenta sadrži broj, taj broj
    nužno postoji u `evidence`. „Sajt je spor" tako ne može da prođe (§3.5).
    """
    return CheckResult(
        check_id=spec.check_id,
        status="finding",
        findings=[
            Finding(
                domain=ctx.domain,
                check_id=spec.check_id,
                level=spec.level,
                category=spec.category,
                severity=severity or spec.base_severity,
                evidence=evidence,
                evidence_urls=[u for u in urls if u],
                variant=variant,
            )
        ],
    )


# --------------------------------------------------------------------------- #
# Preduslovi: `requires` iz §2.4 — zašto provera ne može da se izvrši
# --------------------------------------------------------------------------- #
def _home_ok(snapshot: Any) -> bool:
    home = getattr(snapshot, "home", None)
    return bool(home and home.status == 200 and home.html_bytes)


# Rečenica za neispunjen preduslov je u katalogu pod `requires.<ime>`.
REQUIREMENTS: dict[str, Callable[[Any], bool]] = {
    "entry": lambda s: s.entry is not None,
    "entry_response": lambda s: s.entry is not None and s.entry.status is not None,
    "home": _home_ok,
    "home_html": lambda s: bool(s.home and s.home.raw_html),
    "robots": lambda s: s.robots.status is not None,
    "sitemap": lambda s: s.sitemap.status is not None,
    "soft404": lambda s: len(s.soft404.probes) == 2 and all(p.status is not None for p in s.soft404.probes),
    "browser": lambda s: s.status != "failed",
    "network": lambda s: s.status != "failed" and s.network.request_count > 0,
}


# Provera koja čita polje uvedeno u v2 navodi ga u `requires` kao `v2:<polje>`. Snapshot iz
# 1.x to polje nema, a na njima je kalibrisana lista A: provera je tada `unknown`, nikad
# `ok` sa podrazumevanom vrednošću i nikad pad.
NOVO_POLJE = "v2:"


def unmet(spec: CheckSpec, snapshot: Any) -> Reason | None:
    for name in spec.requires:
        if name.startswith(NOVO_POLJE):
            verzija = getattr(snapshot, "scanner_version", "")
            if verzija.startswith("1."):
                return Reason("v1_snapshot", {"verzija": verzija, "polje": name.removeprefix(NOVO_POLJE)})
            continue
        try:
            ispunjen = REQUIREMENTS[name](snapshot)
        except (AttributeError, TypeError):
            ispunjen = False
        if not ispunjen:
            return Reason(f"requires.{name}")
    return None


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #
def run(level: int, snapshot: Any, ctx: Context) -> list[CheckResult]:
    """Svaka provera u sopstvenom `try`: izuzetak nikad ne napušta domen (§8.2)."""
    results: list[CheckResult] = []
    for spec in sorted(REGISTRY.values(), key=lambda s: s.check_id):
        if spec.level != level:
            continue
        reason = unmet(spec, snapshot)
        if reason:
            results.append(CheckResult(check_id=spec.check_id, status="unknown", reason=reason))
            continue
        try:
            results.append(spec.fn(snapshot, ctx))
        except Exception as exc:  # noqa: BLE001 — granica domena, namerno široka
            results.append(unknown(spec, "check_crashed", greska=f"{type(exc).__name__}: {exc}"))
    return results


def load_all() -> None:
    """Uvozi module sa proverama da bi se dekoratori izvršili."""
    from skener.checks import a11y, i18n, infra, perf, seo, social  # noqa: F401
