"""Ceo prolaz bez komandne linije: nivo 1 → eskalacija → izbor → nivo 2 → bodovanje.

CLI i web worker zovu isti kod, pa se dve kopije redosleda ne mogu razići. Modul ne
štampa, ne čita argumente i ne izlazi iz procesa: greške su `ConfigError` i
`InputError`, a napredak ide kroz `on_event`. Ceo prolaz je jedna async funkcija i radi
u jednoj petlji. Otkazan prolaz zatvara browser i HTTP klijent, a snapshoti domena koji
su već završeni ostaju na disku.
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

from skener import store
from skener.checks import registry
from skener.config import digest, user_agent
from skener.fetch.browser import capture_all
from skener.fetch.http import scan_domains
from skener.inputs import InputError, is_excluded
from skener.models import (
    BrowserSnapshot,
    DomainInput,
    DomainReport,
    DomainStatus,
    Event,
    Reason,
    ScanResult,
    SiteSnapshot,
)
from skener.score import analyze, escalation_reasons, partial_shares, rank, select_for_level2

log = logging.getLogger("skener")

LEVELS = ("1", "2", "auto")
OnEvent = Callable[[Event], None]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Progress:
    """Broji završene domene jedne faze i javlja pozivaocu.

    Greška u pozivaočevoj funkciji se loguje i prolaz ide dalje: traka napretka ne sme
    da izgubi domen čiji je snapshot već na disku.
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
        except Exception:  # noqa: BLE001 — tuđa funkcija ne sme da obori prolaz
            log.exception("on_event pukao na %s; prolaz ide dalje", event.kind)


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
    """Pun prolaz nad listom domena. Snapshot svakog domena ide na disk čim je gotov.

    `excluded` su domeni čiji je administrator tražio da se ne skeniraju. Ne dobijaju
    nijedan zahtev, a u rezultatu je samo njihov broj.
    """
    if level not in LEVELS:
        raise ValueError(f"nivo mora biti jedan od {LEVELS}, a jeste {level!r}")
    targets = list(targets)
    if not targets:
        raise InputError("lista domena je prazna")
    user_agent(config)  # bez identiteta operatera nema nijednog zahteva
    started_at, t0 = _now(), time.monotonic()
    targets, izuzeto = _bez_izuzetih(targets, excluded)

    log.info("nivo 1: %d domena", len(targets))
    progress = _Progress(on_event, "level1", len(targets))
    sites = await scan_domains(
        targets,
        config,
        snapshot_dir=snapshot_dir,
        on_done=lambda site: progress.domain(site.domain, _level1_status(site)),
    )
    progress.finish()
    t1 = time.monotonic()

    reasons, chosen = _escalate(sites, config, level)
    browsers = await _level2(chosen, config, snapshot_dir, on_event)
    t2 = time.monotonic()

    reports = [
        analyze(site, config, browser=browsers.get(site.domain), escalation=reasons.get(site.domain, []))
        for site in sites
    ]
    durations = {"level1": t1 - t0, "level2": t2 - t1, "total": time.monotonic() - t0}
    return _result(reports, started_at, durations, config, browsers.values(), excluded=izuzeto)


def _bez_izuzetih(targets: list[DomainInput], excluded: Sequence[str]) -> tuple[list[DomainInput], int]:
    ostali = [t for t in targets if not is_excluded(t.domain, excluded)]
    izuzeto = len(targets) - len(ostali)
    if izuzeto:
        log.info("izuzeto na zahtev administratora: %d domena", izuzeto)
    return ostali, izuzeto


def _level1_status(site: SiteSnapshot) -> str:
    """Za traku napretka: da li se početna otvorila. Konačan status daje tek bodovanje."""
    return "ok" if site.home is not None and site.home.status == 200 else "failed"


def _escalate(
    sites: Sequence[SiteSnapshot], config: dict, level: str
) -> tuple[dict[str, list[Reason]], list[SiteSnapshot]]:
    """Eskalacija (§6) i gornji limit; vraća razloge za izveštaj i izabrane domene."""
    if level == "1":
        return {}, []

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
        "nivo 2: %d kandidata, %d prolazi, %d preko limita",
        len(candidates),
        len(chosen),
        len(candidates) - len(chosen),
    )
    return reasons, chosen


async def _level2(
    chosen: Sequence[SiteSnapshot], config: dict, snapshot_dir: Path | None, on_event: OnEvent | None
) -> dict[str, BrowserSnapshot]:
    if not chosen or not _playwright_installed("nivo 2 se preskače"):
        return {}
    progress = _Progress(on_event, "level2", len(chosen))
    browsers = await capture_all(
        chosen,
        config,
        snapshot_dir=snapshot_dir,
        on_done=lambda snapshot: progress.domain(snapshot.domain, snapshot.status),
    )
    progress.finish()
    return browsers


def _playwright_installed(posledica: str) -> bool:
    """Nivo 2 je opcion (`pip install 'skener[browser]'`); bez njega nivo 1 i dalje radi."""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        log.error("Playwright nije instaliran; %s (pip install 'skener[browser]')", posledica)
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
    po_imenu = sorted(reports, key=lambda r: r.domain)
    return ScanResult(
        started_at=started_at,
        finished_at=_now(),
        duration_s={name: round(seconds, 2) for name, seconds in durations.items()},
        config_digest=digest(config),
        environment=_environment(browsers),
        summary=summary,
        budget_share=budget_share,
        unknown_share=unknown_share,
        ranked=rank(reports),
        unreachable=[r for r in po_imenu if r.status == "unreachable"],
        not_scanned=[r for r in po_imenu if r.status == "failed"],
    )


def _environment(browsers: Iterable[BrowserSnapshot]) -> dict[str, str | None]:
    """Gde je prolaz rađen. Chromium je iz snapshota, pa `recheck` navodi onaj iz prolaza."""
    chromium = next((b.browser_version for b in browsers if b.browser_version), None)
    return {"os": platform.platform(), "python": platform.python_version(), "chromium": chromium}


# --------------------------------------------------------------------------- #
# recheck — glavno oruđe pri kalibraciji (§11.1)
# --------------------------------------------------------------------------- #
def recheck(snapshot_dir: Path, config: dict, *, on_event: OnEvent | None = None) -> ScanResult:
    """Ponovo boduje sačuvane snapshote, bez ijednog zahteva ka mreži."""
    started_at, t0 = _now(), time.monotonic()
    pairs = list(store.read_all(Path(snapshot_dir)))
    if not pairs:
        raise InputError(f"{snapshot_dir}: nijedan snapshot nije pronađen")

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
# record — snima fixture-e (§12.2)
# --------------------------------------------------------------------------- #
async def record(
    targets: Sequence[DomainInput],
    config: dict,
    *,
    out_dir: Path,
    level: str = "auto",
    excluded: Sequence[str] = (),
) -> int:
    """Snima gzipovane snapshote svih domena; vraća njihov broj. Nivo 2 ide za sve, bez eskalacije."""
    user_agent(config)  # bez identiteta operatera nema nijednog zahteva
    targets, _ = _bez_izuzetih(list(targets), excluded)
    sites = await scan_domains(targets, config)
    for site in sites:
        # Bez sirovog HTML-a ostalih strana, inače repo naraste (§12.2).
        for page in site.pages[1:]:
            page.raw_html = None
        store.write_site(out_dir, site, compress=True)

    if level != "1" and _playwright_installed("snimam samo nivo 1"):
        for snapshot in (await capture_all(sites, config)).values():
            store.write_browser(out_dir, snapshot, compress=True)
    return len(sites)
