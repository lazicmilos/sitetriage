"""The check registry and the engine that runs it.

Checks are **not called from an if-else chain**. Each one registers with its own
metadata and the engine just walks the registry, so the list of checks, the table
in the README and `sitetriage explain` are one and the same data, not three copies
that drift apart. Each check also declares its `requires`: the preconditions that
say why it cannot run on a given snapshot.

The rule that is never broken: this package does not import `httpx`, `playwright`, or
`fetch.*` other than `fetch.urls` (enforced by `tests/test_architecture.py`). If you need
something from the network, the snapshot is missing a field: add the field.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sitetriage.config import get
from sitetriage.models import BrowserSnapshot, CheckResult, Finding, Reason

CheckFn = Callable[[Any, "Context"], CheckResult]


@dataclass
class Context:
    """Everything a check may know: the domain, the thresholds and, for level 1, what level 2 saw."""

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
            raise ValueError(f"duplicate check_id: {check_id}")
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
        # The check body reaches its spec through `fn.spec`, without a registry lookup.
        fn.spec = spec  # type: ignore[attr-defined]
        return fn

    return register


# --------------------------------------------------------------------------- #
# Result constructors: the only way a check may answer
# --------------------------------------------------------------------------- #
def ok(spec: CheckSpec) -> CheckResult:
    return CheckResult(check_id=spec.check_id, status="ok")


def unknown(spec: CheckSpec, reason: str, **evidence: Any) -> CheckResult:
    """`unknown` without a reason is a bug, and the signature does not even allow it.

    The reason is a code from the catalog (`sitetriage.messages`) plus data for the sentence,
    the same as for a finding.
    """
    return CheckResult(check_id=spec.check_id, status="unknown", reason=Reason(reason, evidence))


def not_applicable(spec: CheckSpec, reason: str, **evidence: Any) -> CheckResult:
    """The check has nothing to check on this site; the reason is mandatory, as for `unknown` (ADR-015)."""
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
    """A finding carries evidence; `sitetriage.messages` builds the sentence from it when shown.

    That is not style but a guarantee: if the client sentence contains a number, that number
    necessarily exists in `evidence`. "The site is slow" cannot get through that way (ADR-022).
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
# Requirements (`requires`): why a check cannot run
# --------------------------------------------------------------------------- #
def _home_ok(snapshot: Any) -> bool:
    home = getattr(snapshot, "home", None)
    return bool(home and home.status == 200 and home.html_bytes)


# The sentence for an unmet requirement is in the catalog under `requires.<name>`.
REQUIREMENTS: dict[str, Callable[[Any], bool]] = {
    "entry": lambda s: s.entry is not None,
    "entry_response": lambda s: s.entry is not None and s.entry.status is not None,
    "home": _home_ok,
    "home_html": lambda s: bool(s.home and s.home.raw_html),
    # Home page body cut at `http.max_body_kb`: whatever came after the limit was not seen.
    "home_complete": lambda s: not s.home.truncated,
    "robots": lambda s: s.robots.status is not None,
    "sitemap": lambda s: s.sitemap.status is not None,
    "soft404": lambda s: len(s.soft404.probes) == 2 and all(p.status is not None for p in s.soft404.probes),
    "browser": lambda s: s.status != "failed",
    "network": lambda s: s.status != "failed" and s.network.request_count > 0,
    "host_variants": lambda s: s.host_variants is not None,
    "level2_full": lambda s: not s.light,
    "network_profile": lambda s: s.network_profile is not None,
    "link": lambda s: s.link_mbps is not None,
}


# A check that reads a field introduced in v2 lists it in `requires` as `v2:<field>`. A snapshot
# from 1.x does not have that field, and list A was calibrated on such snapshots: the check is then
# `unknown`, never `ok` with a default value and never a crash.
NEW_FIELD_PREFIX = "v2:"


def unmet(spec: CheckSpec, snapshot: Any) -> Reason | None:
    for name in spec.requires:
        if name.startswith(NEW_FIELD_PREFIX):
            version = getattr(snapshot, "scanner_version", "")
            if version.startswith("1."):
                field = name.removeprefix(NEW_FIELD_PREFIX)
                return Reason("v1_snapshot", {"version": version, "field": field})
            continue
        try:
            met = REQUIREMENTS[name](snapshot)
        except (AttributeError, TypeError):
            met = False
        if not met:
            return Reason(f"requires.{name}")
    return None


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def run(level: int, snapshot: Any, ctx: Context) -> list[CheckResult]:
    """Each check runs in its own `try`: an exception never leaves the domain."""
    results: list[CheckResult] = []
    for spec in sorted(REGISTRY.values(), key=lambda s: s.check_id):
        if spec.level != level:
            continue
        reason = unmet(spec, snapshot)
        if reason:
            # Light level 2 deliberately does not measure time (BUG-020): not an unknown, so not `partial`.
            status = "not_applicable" if reason.code == "requires.level2_full" else "unknown"
            results.append(CheckResult(check_id=spec.check_id, status=status, reason=reason))
            continue
        try:
            results.append(spec.fn(snapshot, ctx))
        except Exception as exc:  # noqa: BLE001 — domain boundary, deliberately broad
            results.append(unknown(spec, "check_crashed", error=f"{type(exc).__name__}: {exc}"))
    return results


def load_all() -> None:
    """Imports the check modules so that their decorators run."""
    from sitetriage.checks import a11y, i18n, infra, perf, seo, social  # noqa: F401
