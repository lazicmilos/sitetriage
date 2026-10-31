"""Findings whose sentences are checked: the test set and one broken case for every check,
plus cases that change the form of a sentence (video, interrupted loading, plural).

The golden file `tests/golden/messages-sr.json` was made from these findings before the
messages were moved out of the checks into the catalog (ADR-009). When a change to a sentence
is intended, the golden file is regenerated and the difference shows in `git diff`.

The case ids (`ispitni/…`, `nivo1/…`, `posebno/…` and the names after them) are the `case`
values of the golden files, so they stay as they were when the files were made.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from factories import CONFIG, clean_browser, clean_site, run_level
from test_checks_level1 import POZITIVNI as LEVEL1
from test_checks_level2 import POZITIVNI as LEVEL2
from test_ispitni_skup import spec_config

from sitetriage import store
from sitetriage.checks import registry
from sitetriage.config import load_config
from sitetriage.models import Finding
from sitetriage.score import analyze

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden" / "messages-sr.json"


def _same(site: Any, field: str, count: int) -> None:
    for i, page in enumerate(site.pages[:count]):
        setattr(page, field, "Ista vrednost na više stranica")
        page.final_url = "https://cist.rs/" if i == 0 else f"https://cist.rs/g{i}/strana"


def _browser(change: Callable[[Any], None]) -> Any:
    browser = clean_browser()
    change(browser)
    return browser


def _site(change: Callable[[Any], None]) -> Any:
    site = clean_site()
    change(site)
    return site


def _findings(level: int, snapshot: Any, industry: str = "other") -> list[Finding]:
    return [f for result in run_level(level, snapshot, industry).values() for f in result.findings]


def finding_cases() -> Iterator[tuple[str, Finding]]:
    registry.load_all()
    for name, config in (("spec", spec_config()), ("toml", load_config())):
        for site, browser in store.read_all(FIXTURES):
            for f in analyze(site, config, browser=browser).findings:
                yield f"ispitni/{name}/{site.domain}", f

    for check_id, breaker in sorted(LEVEL1.items()):
        yield from ((f"nivo1/{check_id}", f) for f in _findings(1, _site(breaker)))
    for check_id, breaker in sorted(LEVEL2.items()):
        yield from ((f"nivo2/{check_id}", f) for f in _findings(2, _browser(breaker)))

    def video(b: Any) -> None:
        b.network.total_bytes = b.network.bytes_at_load = 30_000_000
        b.network.bytes_by_type = b.network.bytes_by_type_at_load = {"media": 8_000_000, "image": 22_000_000}

    def interrupted(b: Any) -> None:
        b.timing.reached = "timeout"
        b.timing.load_ms = None

    def compression(s: Any) -> None:
        s.home.headers = {}
        s.home.html_bytes = 80_000

    special: list[tuple[str, int, Any]] = [
        ("video", 2, _browser(video)),
        ("prekid-ucitavanja", 2, _browser(interrupted)),
        ("kompresija-80kB", 1, _site(compression)),
    ]
    for count in (4, 5, 21):
        special.append((f"h1-{count}", 2, _browser(lambda b, n=count: setattr(b.dom, "h1_count", n))))
    for count in (4, 7, 21):
        special.append((f"konzola-{count}", 2, _browser(lambda b, n=count: setattr(b.console, "errors", n))))
    def requests(b: Any, n: int) -> None:
        b.network.request_count = b.network.requests_at_load = n

    for count in (101, 102, 150):
        special.append((f"zahtevi-{count}", 2, _browser(lambda b, n=count: requests(b, n))))
    for count in (3, 5):
        special.append((f"naslov-{count}", 1, _site(lambda s, n=count: _same(s, "title", n))))
        special.append((f"opis-{count}", 1, _site(lambda s, n=count: _same(s, "meta_description", n))))
    for name, level, snapshot in special:
        yield from ((f"posebno/{name}", f) for f in _findings(level, snapshot))


# --------------------------------------------------------------------------- #
# Reasons: why something was not checked and why a domain goes to level 2
# --------------------------------------------------------------------------- #
GOLDEN_REASONS = Path(__file__).parent / "golden" / "reasons-sr.json"


def _unknowns(level: int, snapshot: Any) -> Iterator[tuple[str, Any]]:
    for result in run_level(level, snapshot).values():
        if result.status == "unknown":
            yield result.check_id, result.reason


def reason_cases() -> Iterator[tuple[str, str, Any]]:
    """(case, check or "eskalacija", reason) for every path that produces a reason."""
    from sitetriage.models import BrowserSnapshot, Entry, SiteSnapshot, SnapshotError, Soft404Probe
    from sitetriage.score import escalation_reasons

    def site(change: Callable[[Any], None]) -> Any:
        return _site(change)

    def browser(change: Callable[[Any], None]) -> Any:
        return _browser(change)

    def no_response(s: Any) -> None:
        s.entry = Entry(requested_url="https://cist.rs/", error_kind="connect_timeout")

    def tls_over_http(s: Any) -> None:
        s.entry.requested_url = "http://cist.rs/"
        s.errors = [SnapshotError("entry", "tls_handshake", "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF")]

    def probes_403(s: Any) -> None:
        s.soft404.probes = [Soft404Probe(url=p.url, status=403) for p in s.soft404.probes]

    def interrupted(b: Any) -> None:
        b.timing.reached = "timeout"
        b.timing.load_ms = None
        b.dom.h1_count = 0
        b.dom.images_total = 0

    def unmeasured_images(b: Any) -> None:
        b.dom.images_total = 10
        b.dom.images_unmeasured = 6

    level1 = {
        "prazan-snapshot": SiteSnapshot(domain="cist.rs"),
        "bez-odgovora": site(no_response),
        "tls-preko-http": site(tls_over_http),
        "sitemap-403": site(lambda s: (setattr(s.sitemap, "status", 403), s.sitemap.urls.clear())),
        "robots-403": site(lambda s: setattr(s.robots, "status", 403)),
        "sonde-403": site(probes_403),
        "malo-teksta": site(lambda s: setattr(s.home, "text_length", 100)),
        "pukla-provera": site(lambda s: setattr(s.home, "headers", None)),
    }
    for name, snapshot in level1.items():
        yield from ((f"nivo1/{name}", c, r) for c, r in _unknowns(1, snapshot))

    level2 = {
        "browser-pao": BrowserSnapshot(domain="cist.rs", status="failed"),
        "bez-saobracaja": browser(lambda b: setattr(b.network, "request_count", 0)),
        "nemereni-odgovori": browser(lambda b: setattr(b.network, "unmeasured_at_load", 9)),
        "prekid-ucitavanja": browser(interrupted),
        "vreme-nije-mereno": browser(lambda b: setattr(b.timing, "load_ms", None)),
        "nemerene-slike": browser(unmeasured_images),
    }
    for name, snapshot in level2.items():
        yield from ((f"nivo2/{name}", c, r) for c, r in _unknowns(2, snapshot))

    def everything_for_escalation(s: Any) -> None:
        s.home.text_length = 300
        s.home.h1_count_raw = 0
        s.home.html_bytes = 400_000
        s.home.headers = {}
        s.home.meta_description = None
        s.entry.elapsed_ms = 2_000

    escalated = site(everything_for_escalation)
    results = list(run_level(1, escalated).values())
    yield from (("eskalacija", "eskalacija", r) for r in escalation_reasons(escalated, results, CONFIG))
