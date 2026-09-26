"""Nalazi nad kojima se proveravaju rečenice: ispitni skup i po jedan pokvaren slučaj za svaku
proveru, uz slučajeve koji menjaju oblik rečenice (video, prekid učitavanja, množina).

Golden fajl `tests/golden/poruke-sr.json` napravljen je iz ovih nalaza pre nego što su poruke
izdvojene iz provera. Kad izmena rečenice u F2 bude namerna, golden se pravi ponovo i razlika
je vidljiva u `git diff`-u.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from factories import CONFIG, clean_browser, clean_site, run_level
from test_checks_level1 import POZITIVNI as NIVO1
from test_checks_level2 import POZITIVNI as NIVO2
from test_ispitni_skup import spec_config

from skener import store
from skener.checks import registry
from skener.config import load_config
from skener.models import Finding
from skener.score import analyze

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden" / "poruke-sr.json"


def _isti(site: Any, polje: str, broj: int) -> None:
    for i, page in enumerate(site.pages[:broj]):
        setattr(page, polje, "Ista vrednost na više stranica")
        page.final_url = "https://cist.rs/" if i == 0 else f"https://cist.rs/g{i}/strana"


def _browser(izmena: Callable[[Any], None]) -> Any:
    browser = clean_browser()
    izmena(browser)
    return browser


def _site(izmena: Callable[[Any], None]) -> Any:
    site = clean_site()
    izmena(site)
    return site


def _nalazi(level: int, snapshot: Any, industry: str = "ostalo") -> list[Finding]:
    return [f for result in run_level(level, snapshot, industry).values() for f in result.findings]


def slucajevi() -> Iterator[tuple[str, Finding]]:
    registry.load_all()
    for naziv, config in (("spec", spec_config()), ("toml", load_config())):
        for site, browser in store.read_all(FIXTURES):
            for f in analyze(site, config, browser=browser).findings:
                yield f"ispitni/{naziv}/{site.domain}", f

    for check_id, pokvari in sorted(NIVO1.items()):
        yield from ((f"nivo1/{check_id}", f) for f in _nalazi(1, _site(pokvari)))
    for check_id, pokvari in sorted(NIVO2.items()):
        yield from ((f"nivo2/{check_id}", f) for f in _nalazi(2, _browser(pokvari)))

    def video(b: Any) -> None:
        b.network.total_bytes = b.network.bytes_at_load = 30_000_000
        b.network.bytes_by_type = b.network.bytes_by_type_at_load = {"media": 8_000_000, "image": 22_000_000}

    def prekid(b: Any) -> None:
        b.timing.reached = "timeout"
        b.timing.load_ms = None

    def kompresija(s: Any) -> None:
        s.home.headers = {}
        s.home.html_bytes = 80_000

    posebni: list[tuple[str, int, Any]] = [
        ("video", 2, _browser(video)),
        ("prekid-ucitavanja", 2, _browser(prekid)),
        ("kompresija-80kB", 1, _site(kompresija)),
    ]
    for broj in (4, 5, 21):
        posebni.append((f"h1-{broj}", 2, _browser(lambda b, n=broj: setattr(b.dom, "h1_count", n))))
    for broj in (4, 7, 21):
        posebni.append((f"konzola-{broj}", 2, _browser(lambda b, n=broj: setattr(b.console, "errors", n))))
    def zahtevi(b: Any, n: int) -> None:
        b.network.request_count = b.network.requests_at_load = n

    for broj in (101, 102, 150):
        posebni.append((f"zahtevi-{broj}", 2, _browser(lambda b, n=broj: zahtevi(b, n))))
    for broj in (3, 5):
        posebni.append((f"naslov-{broj}", 1, _site(lambda s, n=broj: _isti(s, "title", n))))
        posebni.append((f"opis-{broj}", 1, _site(lambda s, n=broj: _isti(s, "meta_description", n))))
    for naziv, level, snapshot in posebni:
        yield from ((f"posebno/{naziv}", f) for f in _nalazi(level, snapshot))


# --------------------------------------------------------------------------- #
# Razlozi: zašto nešto nije provereno i zašto domen ide na nivo 2
# --------------------------------------------------------------------------- #
GOLDEN_RAZLOZI = Path(__file__).parent / "golden" / "razlozi-sr.json"


def _nepoznati(level: int, snapshot: Any) -> Iterator[tuple[str, Any]]:
    for result in run_level(level, snapshot).values():
        if result.status == "unknown":
            yield result.check_id, result.reason


def razlozi() -> Iterator[tuple[str, str, Any]]:
    """(slučaj, provera ili „eskalacija", razlog) za svaki put koji daje razlog."""
    from skener.models import BrowserSnapshot, Entry, SiteSnapshot, SnapshotError, Soft404Probe
    from skener.score import escalation_reasons

    def site(izmena: Callable[[Any], None]) -> Any:
        return _site(izmena)

    def browser(izmena: Callable[[Any], None]) -> Any:
        return _browser(izmena)

    def bez_odgovora(s: Any) -> None:
        s.entry = Entry(requested_url="https://cist.rs/", error_kind="connect_timeout")

    def tls_preko_http(s: Any) -> None:
        s.entry.requested_url = "http://cist.rs/"
        s.errors = [SnapshotError("entry", "tls_handshake", "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF")]

    def sonde_403(s: Any) -> None:
        s.soft404.probes = [Soft404Probe(url=p.url, status=403) for p in s.soft404.probes]

    def prekid(b: Any) -> None:
        b.timing.reached = "timeout"
        b.timing.load_ms = None
        b.dom.h1_count = 0
        b.dom.images_total = 0

    def nemerene_slike(b: Any) -> None:
        b.dom.images_total = 10
        b.dom.images_unmeasured = 6

    nivo1 = {
        "prazan-snapshot": SiteSnapshot(domain="cist.rs"),
        "bez-odgovora": site(bez_odgovora),
        "tls-preko-http": site(tls_preko_http),
        "sitemap-403": site(lambda s: setattr(s.sitemap, "status", 403)),
        "robots-403": site(lambda s: setattr(s.robots, "status", 403)),
        "sonde-403": site(sonde_403),
        "malo-teksta": site(lambda s: setattr(s.home, "text_length", 100)),
        "pukla-provera": site(lambda s: setattr(s.home, "headers", None)),
    }
    for naziv, snapshot in nivo1.items():
        yield from ((f"nivo1/{naziv}", c, r) for c, r in _nepoznati(1, snapshot))

    nivo2 = {
        "browser-pao": BrowserSnapshot(domain="cist.rs", status="failed"),
        "bez-saobracaja": browser(lambda b: setattr(b.network, "request_count", 0)),
        "nemereni-odgovori": browser(lambda b: setattr(b.network, "unmeasured_at_load", 9)),
        "prekid-ucitavanja": browser(prekid),
        "vreme-nije-mereno": browser(lambda b: setattr(b.timing, "load_ms", None)),
        "nemerene-slike": browser(nemerene_slike),
    }
    for naziv, snapshot in nivo2.items():
        yield from ((f"nivo2/{naziv}", c, r) for c, r in _nepoznati(2, snapshot))

    def sve_za_eskalaciju(s: Any) -> None:
        s.home.text_length = 300
        s.home.h1_count_raw = 0
        s.home.html_bytes = 400_000
        s.home.headers = {}
        s.home.meta_description = None
        s.entry.elapsed_ms = 2_000

    eskalacija = site(sve_za_eskalaciju)
    rezultati = list(run_level(1, eskalacija).values())
    yield from (("eskalacija", "eskalacija", r) for r in escalation_reasons(eskalacija, rezultati, CONFIG))
