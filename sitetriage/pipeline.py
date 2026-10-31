"""A whole run without the command line: level 1 → escalation → selection → level 2 → scoring.

The CLI and the web worker call the same code, so two copies of the order cannot drift apart. The
module does not print, read arguments or exit the process: errors are `ConfigError` and
`InputError`, and progress goes through `on_event`. The whole run is one async function and runs
in one event loop. A cancelled run closes the browser and the HTTP client, and the snapshots of
domains that are already finished stay on disk.
"""

from __future__ import annotations

import logging
import platform
import time
import typing
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sitetriage import store
from sitetriage.checks import registry
from sitetriage.config import digest, user_agent
from sitetriage.fetch.browser import capture_all
from sitetriage.fetch.http import scan_domains
from sitetriage.inputs import InputError, is_excluded
from sitetriage.models import (
    BrowserSnapshot,
    DomainInput,
    DomainReport,
    DomainStatus,
    Event,
    Reason,
    ScanResult,
    SiteSnapshot,
)
from sitetriage.score import analyze, escalation_reasons, partial_shares, rank, select_for_level2

log = logging.getLogger("sitetriage")

LEVELS = ("1", "2", "auto")
OnEvent = Callable[[Event], None]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Progress:
    """Counts the finished domains of one phase and reports them to the caller.

    An error in the caller's function is logged and the run goes on: a progress bar must not
    lose a domain whose snapshot is already on disk.
    """

    def __init__(self, on_event: OnEvent | None, phase: str, total: int) -> None:
        self.on_event = on_event
        self.phase = phase
        self.total = total
        self.done = 0
        self._send(Event("phase_started", phase, total))

    def domain(self, domain: str, status: str) -> None:
        self.done += 1
        self._send(Event("domain_finished", self.phase, self.total, self.done, domain, status))

    def finish(self) -> None:
        self._send(Event("phase_finished", self.phase, self.total, self.done))

    def _send(self, event: Event) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 — someone else's function must not bring down the run
            log.exception("on_event failed on %s; the run goes on", event.kind)


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
async def scan(
    targets: Sequence[DomainInput],
    config: dict,
    *,
    level: str = "auto",
    snapshot_dir: Path | None = None,
    excluded: Sequence[str] = (),
    on_event: OnEvent | None = None,
) -> ScanResult:
    """A full run over the domain list. Every domain's snapshot goes to disk as soon as it is done.

    `excluded` are domains whose administrator asked not to be scanned. They get not a single
    request, and the result holds only their count.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    targets = list(targets)
    if not targets:
        raise InputError("the domain list is empty")
    user_agent(config)  # without an operator identity there is not a single request
    started_at, t0 = _now(), time.monotonic()
    targets, excluded_count = _without_excluded(targets, excluded)

    log.info("level 1: %d domains", len(targets))
    progress = _Progress(on_event, "level1", len(targets))
    sites = await scan_domains(
        targets,
        config,
        snapshot_dir=snapshot_dir,
        on_done=lambda site: progress.domain(site.domain, _level1_status(site)),
    )
    progress.finish()
    t1 = time.monotonic()

    reasons, chosen, rest = _escalate(sites, config, level)
    browsers = await _level2(chosen, config, snapshot_dir, on_event)
    t2 = time.monotonic()
    # After full level 2, so the light measurement does not share the link with time measurement (BUG-006).
    browsers |= await _level2(rest, config, snapshot_dir, on_event, light=True)
    t3 = time.monotonic()

    reports = [
        analyze(site, config, browser=browsers.get(site.domain), escalation=reasons.get(site.domain, []))
        for site in sites
    ]
    durations = {
        "level1": t1 - t0,
        "level2": t2 - t1,
        "level2_light": t3 - t2,
        "total": time.monotonic() - t0,
    }
    return _result(reports, started_at, durations, config, browsers.values(), excluded=excluded_count)


def _without_excluded(targets: list[DomainInput], excluded: Sequence[str]) -> tuple[list[DomainInput], int]:
    remaining = [t for t in targets if not is_excluded(t.domain, excluded)]
    excluded_count = len(targets) - len(remaining)
    if excluded_count:
        log.info("excluded at the administrator's request: %d domains", excluded_count)
    return remaining, excluded_count


def _level1_status(site: SiteSnapshot) -> str:
    """For the progress bar: whether the home page opened. Only scoring gives the final status."""
    return "ok" if site.home is not None and site.home.status == 200 else "failed"


def _escalate(
    sites: Sequence[SiteSnapshot], config: dict, level: str
) -> tuple[dict[str, list[Reason]], list[SiteSnapshot], list[SiteSnapshot]]:
    """Escalation and its cap; returns the reasons for the report, the chosen domains and the rest.

    The rest are sites with a working home page but without a place on full level 2. Fast, clean HTML
    says nothing about page weight: on list B two pages of 4.8 and 4.9 MB had no reason to escalate,
    so they stood at "0 findings" (BUG-020). That is why they get the light measurement.
    """
    if level == "1":
        return {}, [], []

    registry.load_all()
    candidates: list[tuple[SiteSnapshot, list]] = []
    reasons: dict[str, list[Reason]] = {}
    for site in sites:
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        results = registry.run(1, site, ctx)
        why = escalation_reasons(site, results, config)
        if why or level == "2":
            candidates.append((site, results))
            reasons[site.domain] = why or [Reason("forced_level2")]

    chosen = select_for_level2(candidates, config)
    log.info(
        "level 2: %d candidates, %d pass, %d over the cap",
        len(candidates),
        len(chosen),
        len(candidates) - len(chosen),
    )
    chosen_domains = {site.domain for site in chosen}
    rest = [s for s in sites if _level1_status(s) == "ok" and s.domain not in chosen_domains]
    return reasons, chosen, rest


async def _level2(
    chosen: Sequence[SiteSnapshot],
    config: dict,
    snapshot_dir: Path | None,
    on_event: OnEvent | None,
    light: bool = False,
) -> dict[str, BrowserSnapshot]:
    if not chosen or not _playwright_installed("skipping level 2"):
        return {}
    progress = _Progress(on_event, "level2_light" if light else "level2", len(chosen))
    browsers = await capture_all(
        chosen,
        config,
        snapshot_dir=snapshot_dir,
        on_done=lambda snapshot: progress.domain(snapshot.domain, snapshot.status),
        light=light,
    )
    progress.finish()
    return browsers


def _playwright_installed(consequence: str) -> bool:
    """Level 2 is optional (`pip install 'sitetriage[browser]'`); without it level 1 still works."""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        log.error("Playwright is not installed; %s (pip install 'sitetriage[browser]')", consequence)
        return False
    return True


def _result(
    reports: list[DomainReport],
    started_at: str,
    durations: dict[str, float],
    config: dict,
    browsers: Iterable[BrowserSnapshot],
    *,
    excluded: int = 0,
) -> ScanResult:
    counts = Counter(report.status for report in reports)
    counts["excluded"] = excluded
    summary = {status: counts[status] for status in typing.get_args(DomainStatus)}
    for cause in ("budget", "unknown"):
        summary[f"partial_{cause}"] = sum(cause in r.partial_causes for r in reports)
    budget_share, unknown_share = partial_shares(reports)
    by_name = sorted(reports, key=lambda r: r.domain)
    return ScanResult(
        started_at=started_at,
        finished_at=_now(),
        duration_s={name: round(seconds, 2) for name, seconds in durations.items()},
        config_digest=digest(config),
        profile=config.get("profile") or None,
        environment=_environment(browsers),
        summary=summary,
        budget_share=budget_share,
        unknown_share=unknown_share,
        ranked=rank(reports),
        unreachable=[r for r in by_name if r.status == "unreachable"],
        not_scanned=[r for r in by_name if r.status == "failed"],
    )


def _environment(browsers: Iterable[BrowserSnapshot]) -> dict[str, typing.Any]:
    """Where the run was done. Chromium and the network profile come from the snapshots, so `recheck`
    names the ones from the run; `null` when level 2 did not run or the snapshot predates the network
    profile (ADR-010)."""
    browsers = list(browsers)
    chromium = next((b.browser_version for b in browsers if b.browser_version), None)
    profile = next((b.network_profile for b in browsers if b.network_profile), None)
    link_mbps = next((b.link_mbps for b in browsers if b.link_mbps is not None), None)
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "chromium": chromium,
        "network_profile": profile,
        "link_mbps": link_mbps,
    }


# --------------------------------------------------------------------------- #
# recheck — the main calibration tool
# --------------------------------------------------------------------------- #
def recheck(snapshot_dir: Path, config: dict, *, on_event: OnEvent | None = None) -> ScanResult:
    """Scores saved snapshots again, without a single network request."""
    started_at, t0 = _now(), time.monotonic()
    pairs = list(store.read_all(Path(snapshot_dir)))
    if not pairs:
        raise InputError(f"{snapshot_dir}: no snapshot found")

    registry.load_all()
    progress = _Progress(on_event, "recheck", len(pairs))
    reports = []
    for site, browser in pairs:
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        reasons = escalation_reasons(site, registry.run(1, site, ctx), config)
        report = analyze(site, config, browser=browser, escalation=reasons)
        reports.append(report)
        progress.domain(site.domain, report.status)
    progress.finish()
    browsers = [browser for _, browser in pairs if browser is not None]
    return _result(reports, started_at, {"total": time.monotonic() - t0}, config, browsers)


# --------------------------------------------------------------------------- #
# record — records fixtures
# --------------------------------------------------------------------------- #
async def record(
    targets: Sequence[DomainInput],
    config: dict,
    *,
    out_dir: Path,
    level: str = "auto",
    excluded: Sequence[str] = (),
) -> int:
    """Records gzipped snapshots of all domains and returns their count. Level 2 runs for all of them."""
    user_agent(config)  # without an operator identity there is not a single request
    targets, _ = _without_excluded(list(targets), excluded)
    sites = await scan_domains(targets, config)
    for site in sites:
        # Without the raw HTML of the other pages, otherwise the repository grows.
        for page in site.pages[1:]:
            page.raw_html = None
        store.write_site(out_dir, site, compress=True)

    if level != "1" and _playwright_installed("recording level 1 only"):
        for snapshot in (await capture_all(sites, config)).values():
            store.write_browser(out_dir, snapshot, compress=True)
    return len(sites)
