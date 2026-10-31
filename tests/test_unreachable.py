"""ADR-013: a site that does not open goes to the "Ne rade" (unreachable) list, not to the ranking.

`unreachable` is given only when the state is certain, and only after two attempts at least
`http.second_attempt_after_s` apart: the name does not exist in DNS, or no TCP connection was
established on either https or http. Everything else is `failed`, because the site may work and
we just did not see it.
"""

from __future__ import annotations

import asyncio
import csv
import socket
import struct
import threading
import time

import httpcore
import httpx
import jsonschema
import pytest
from factories import clean_site
from localserver import html
from test_json import SEMA

from sitetriage import pipeline, store
from sitetriage.config import load_config
from sitetriage.fetch import http
from sitetriage.fetch.http import Outcome, _classify
from sitetriage.messages import reason, render
from sitetriage.models import DomainInput, Entry, SnapshotError, to_jsonable
from sitetriage.report import csv_out, html_out
from sitetriage.score import analyze

DOMAIN = "ne-rade.test"
OUTCOMES = {
    "nxdomain": ("dns_nxdomain", "[Errno -2] Name or service not known"),
    "no_address": ("dns_nodata", "[Errno -5] No address associated with hostname"),
    "dns_temporary": ("dns_temporary", "[Errno -3] Temporary failure in name resolution"),
    "no_connection": ("no_connection", "[Errno 111] Connection refused"),
    "handshake": ("tls_handshake", "[SSL: UNEXPECTED_EOF_WHILE_READING]"),
    "blocked": ("blocked", "address is not public: ne-rade.test → 10.0.0.5"),
}


def _run(monkeypatch, table: dict, *, after_s: float = 0.0):
    """`scan_domains` over one domain, with the real order of attempts.

    `table[(attempt, scheme)]` is the outcome of the home page request: a name from `OUTCOMES` or an
    HTTP status. Whatever is not in the table returns 200. Returns the snapshot and (start, end) of
    every attempt.
    """
    monkeypatch.setattr("sitetriage.fetch.http.random.uniform", lambda *_: 0)
    attempts: list[tuple[float, float]] = []
    real = http.fetch_site

    class ByTable(http.Fetcher):
        attempt = 0

        async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
            if url not in (f"https://{DOMAIN}/", f"http://{DOMAIN}/"):
                return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")
            outcome = table.get((self.attempt, url.split("://")[0]), 200)
            if isinstance(outcome, str):
                return Outcome(url=url, error_kind=OUTCOMES[outcome][0], error_detail=OUTCOMES[outcome][1])
            return Outcome(url=url, status=outcome, final_url=url, redirect_chain=[url], body=html("Početna"))

    async def counter(fetcher, target):
        fetcher.attempt += 1
        start = time.monotonic()
        snapshot = await real(fetcher, target)
        attempts.append((start, time.monotonic()))
        return snapshot

    monkeypatch.setattr(http, "Fetcher", ByTable)
    monkeypatch.setattr(http, "fetch_site", counter)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["http"]["second_attempt_after_s"] = after_s
    [snapshot] = asyncio.run(http.scan_domains([DomainInput(DOMAIN)], cfg))
    return snapshot, attempts


def _both(scheme: str, outcome) -> dict:
    return {(1, scheme): outcome, (2, scheme): outcome}


# --------------------------------------------------------------------------- #
# Decision table from ADR-013: what is `unreachable` and what is `failed`
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "table, status, cause, attempt_count",
    [
        pytest.param(_both("https", "nxdomain"), "unreachable", "dns", 2, id="tab-name-does-not-exist"),
        pytest.param(_both("https", "no_address"), "unreachable", "dns", 2, id="tab-name-without-address"),
        pytest.param(
            {**_both("https", "no_connection"), **_both("http", "no_connection")},
            "unreachable", "no_response", 2, id="tab-no-connection-on-https-and-http",
        ),
        pytest.param(_both("https", "dns_temporary"), "failed", None, 1, id="tab-dns-temporary"),
        pytest.param(
            {**_both("https", "handshake"), **_both("http", "no_connection")},
            "failed", None, 1, id="tab-tls-handshake-and-http-unreachable",
        ),
        pytest.param(
            {**_both("https", "no_connection"), **_both("http", 403)},
            "failed", None, 1, id="tab-http-response-403",
        ),
        pytest.param(_both("https", 503), "failed", None, 1, id="tab-http-response-503"),
        pytest.param(_both("https", "blocked"), "failed", None, 1, id="tab-ssrf-block"),
    ],
)
def test_unreachable_only_when_certain(monkeypatch, table, status, cause, attempt_count):
    snapshot, attempts = _run(monkeypatch, table)
    report = analyze(snapshot, load_config())
    assert report.status == status
    assert len(attempts) == attempt_count == len(snapshot.entry_attempts)
    findings = [f for f in report.findings if f.check_id == "infra.unreachable"]
    if cause is None:
        assert not findings and report.reason is not None, "`failed` has a reason for the not scanned list"
        return
    [finding] = findings
    assert finding.severity == "critical" and finding.category == "infra"
    assert finding.evidence["cause"] == cause and finding.evidence["attempt_count"] == 2
    assert [finding.evidence["first_attempt"], finding.evidence["second_attempt"]] == snapshot.entry_attempts
    assert all(t.endswith("Z") for t in snapshot.entry_attempts)


def test_second_attempt_that_succeeds_scans_the_site_normally(monkeypatch):
    snapshot, attempts = _run(monkeypatch, {(1, "https"): "nxdomain"})
    report = analyze(snapshot, load_config())
    assert len(attempts) == 2
    assert snapshot.entry.status == 200 and snapshot.robots.status == 404, "the full run follows the entry"
    assert report.status in ("scanned", "partial")
    assert "infra.unreachable" not in {f.check_id for f in report.findings}


def test_second_attempt_waits_at_least_the_configured_time(monkeypatch):
    _, attempts = _run(monkeypatch, _both("https", "nxdomain"), after_s=0.3)
    (_, first_end), (second_start, _) = attempts
    assert second_start - first_end >= 0.3


@pytest.mark.parametrize(
    "errno, kind",
    [
        pytest.param(socket.EAI_NONAME, "dns_nxdomain", id="ke-name-does-not-exist"),
        pytest.param(
            socket.EAI_NODATA,
            "dns_nodata",
            id="ke-name-without-address",
            marks=pytest.mark.skipif(socket.EAI_NODATA == socket.EAI_NONAME, reason="same code on Windows"),
        ),
        pytest.param(socket.EAI_AGAIN, "dns_temporary", id="ke-temporary"),
        pytest.param(socket.EAI_FAIL, "dns", id="ke-other"),
    ],
)
def test_dns_error_is_classified_by_errno(errno, kind):
    """Compared with the constants from `socket`: the numbers differ between Linux and Windows."""
    try:
        try:
            raise socket.gaierror(errno, "dns")
        except socket.gaierror as cause:
            raise httpx.ConnectError("error", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == kind


def test_eai_again_is_not_unreachable(monkeypatch):
    async def temporary(host, port):
        raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")

    monkeypatch.setattr(http, "_resolve", temporary)
    cfg = load_config()
    cfg["http"]["second_attempt_after_s"] = 0
    [snapshot] = asyncio.run(http.scan_domains([DomainInput(DOMAIN)], cfg))
    report = analyze(snapshot, cfg)
    assert snapshot.entry.error_kind == "dns_temporary"
    assert len(snapshot.entry_attempts) == 1, "a temporary DNS error does not look like an unreachable site"
    assert report.status == "failed"
    assert "DNS privremeno nedostupan" in reason(report.reason, "sr")


# --------------------------------------------------------------------------- #
# A drop after an established TCP connection is not "no connection": the server is there,
# it just does not answer us (BUG-004)
# --------------------------------------------------------------------------- #
class ClosesConnection:
    """Accepts a TCP connection and closes it at once, before TLS; `reset` sends RST instead of FIN."""

    def __init__(self, *, reset: bool) -> None:
        self.reset = reset
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self.sock.accept()
            except OSError:
                return
            if self.reset:
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            connection.close()


def _entry(domain: str, allowed: str):
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["net"]["allowed_private"] = [allowed]

    async def run():
        async with http.Fetcher(cfg) as fetcher:
            return await http.fetch_site(fetcher, DomainInput(domain))

    return asyncio.run(run())


@pytest.mark.parametrize("reset", [False, True], ids=["st-closes", "st-resets"])
def test_interrupted_tls_handshake_is_not_unreachable(reset):
    server = ClosesConnection(reset=reset)
    try:
        snapshot = _entry(f"https://127.0.0.1:{server.port}", f"127.0.0.1:{server.port}")
    finally:
        server.sock.close()
    assert snapshot.entry.status is None
    assert snapshot.entry.error_kind != "no_connection", snapshot.entry.error_detail
    assert snapshot.entry_unreachable() is None


@pytest.mark.parametrize(
    "error, cause, no_connection",
    [
        # An RST can arrive before `connect` returns; the server still accepted the connection.
        pytest.param(httpcore.ConnectError("x"), ConnectionResetError(104, "reset"), False, id="st-reset"),
        pytest.param(httpcore.ConnectTimeout(""), None, True, id="st-timeout"),
    ],
)
def test_tcp_error_that_is_and_is_not_no_connection(monkeypatch, error, cause, no_connection):
    error.__cause__ = cause

    async def public(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class Fails(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **_kwargs):
            raise error

    monkeypatch.setattr(http, "_resolve", public)
    backend = http._PublicAddresses(Fails(), frozenset())
    with pytest.raises(httpcore.ConnectError) as caught:
        asyncio.run(backend.connect_tcp("primer.rs", 443))
    assert isinstance(caught.value, http.NoConnection) is no_connection


def test_refused_tcp_connection_is_no_connection():
    with socket.create_server(("127.0.0.1", 0)) as taken:
        port = taken.getsockname()[1]
    snapshot = _entry(f"http://127.0.0.1:{port}", f"127.0.0.1:{port}")
    assert snapshot.entry.error_kind == "no_connection"


# --------------------------------------------------------------------------- #
# Reports: "Ne rade" (unreachable) after the ranking, "Nije skenirano" (not scanned) with a reason
# --------------------------------------------------------------------------- #
def _ne_radi(domain: str = "ugasen.rs", cause: str = "dns"):
    attempts = ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]
    site = clean_site(domain=domain, pages=[], entry_attempts=attempts)
    kind = "dns_nxdomain" if cause == "dns" else "no_connection"
    site.entry = Entry(requested_url=f"https://{domain}/", error_kind=kind, error_detail="detail")
    if cause == "no_response":
        site.errors = [SnapshotError("entry", "no_connection", "refused")] * 2
    return site


def _not_scanned(domain: str = "zatvoren.rs"):
    site = clean_site(domain=domain)
    site.entry.status = 403
    site.pages[0].status = 403
    return site


def test_v1_snapshot_without_response_is_unknown():
    """A 1.x snapshot has neither a second attempt nor a DNS error kind: it is not known, not "working"."""
    site = _ne_radi()
    site.scanner_version = "1.0.0"
    site.entry.error_kind = "dns"
    report = analyze(site, load_config())
    assert report.status == "failed"
    [unknown] = [u for u in report.unknowns if u.check_id == "infra.unreachable"]
    assert unknown.reason.code == "v1_snapshot"


@pytest.mark.parametrize(
    "change, code",
    [
        pytest.param(lambda s: setattr(s, "entry", None), "entry_missing", id="ke-no-entry"),
        pytest.param(lambda s: setattr(s.entry, "status", 403), "entry_status", id="ke-http-status"),
        pytest.param(lambda s: setattr(s.entry, "error_kind", "blocked"), "entry_error", id="ke-error"),
    ],
)
def test_not_scanned_has_a_reason(change, code):
    site = clean_site(pages=[])
    site.entry.status = None
    change(site)
    report = analyze(site, load_config())
    assert report.status == "failed" and report.reason.code == code
    assert "{" not in reason(report.reason, "en")


def test_error_reason_carries_the_detail():
    site = clean_site(pages=[])
    site.entry.status = None
    site.entry.error_kind, site.entry.error_detail = "tls_handshake", "EOF occurred in violation of protocol"
    assert analyze(site, load_config()).reason.evidence["detail"] == "EOF occurred in violation of protocol"


def test_unreachable_is_not_in_the_ranking(tmp_path):
    for site in (_ne_radi(), _not_scanned(), clean_site(domain="radi.rs")):
        store.write_site(tmp_path, site)
    result = pipeline.recheck(tmp_path, load_config())
    assert [r.domain for r in result.ranked] == ["radi.rs"] and result.ranked[0].rank == 1
    assert [r.domain for r in result.unreachable] == ["ugasen.rs"]
    assert [r.domain for r in result.not_scanned] == ["zatvoren.rs"]
    assert result.summary["unreachable"] == 1 and result.summary["failed"] == 1
    assert result.unreachable[0].rank == 0 and result.not_scanned[0].rank == 0
    jsonschema.validate(to_jsonable(result), SEMA)


@pytest.mark.parametrize(
    "cause, lang, expected",
    [
        pytest.param("dns", "sr", "2 pokušaja", id="sr-dns-count"),
        pytest.param("dns", "sr", "domen nema zapis koji ga povezuje sa serverom", id="sr-dns"),
        pytest.param("dns", "en", "2 attempts", id="en-dns-count"),
        pytest.param("dns", "en", "the domain has no record that connects it to a server", id="en-dns"),
        pytest.param("no_response", "sr", "ni preko https ni preko http", id="sr-no-response"),
        pytest.param("no_response", "en", "over neither https nor http", id="en-no-response"),
    ],
)
def test_sentence_says_when_how_often_and_what_happened(cause, lang, expected):
    finding = analyze(_ne_radi(cause=cause), load_config()).findings[0]
    message = render(finding, lang).client
    assert expected in message, message
    assert "2026-09-22 09:00" in message and "2026-09-22 09:01" in message, message


def test_html_has_unreachable_and_not_scanned_sections():
    config = load_config()
    reports = [analyze(s, config) for s in (clean_site(domain="radi.rs"), _ne_radi(), _not_scanned())]
    page = html_out.render(reports, config, excluded=2)

    def section(heading: str) -> int:
        return page.index(f"<h2>{heading}</h2>")

    ranked, unreachable = section("Rangirani domeni"), section("Ne rade")
    not_scanned, by_domain = section("Nije skenirano"), section("Po domenu")
    assert ranked < unreachable < not_scanned < by_domain
    assert "ugasen.rs" not in page[ranked:unreachable] + page[by_domain:], "not in the ranking"
    assert "ugasen.rs" in page[unreachable:not_scanned]
    not_scanned_part = page[not_scanned:by_domain]
    assert "zatvoren.rs" in not_scanned_part and "početna je vratila status 403" in not_scanned_part
    assert "Izuzeto na zahtev administratora: 2" in not_scanned_part


def test_email_draft_for_unreachable_site_is_separate():
    report = analyze(_ne_radi(), load_config())
    draft = html_out.email_draft(report)
    assert "primetio sledeće" not in draft
    assert "ugasen.rs" in draft and "domen nema zapis koji ga povezuje sa serverom" in draft


def test_summary_csv_has_every_domain_with_its_status(tmp_path):
    config = load_config()
    reports = [analyze(s, config) for s in (clean_site(domain="radi.rs"), _ne_radi(), _not_scanned())]
    path = csv_out.write_summary(tmp_path / "summary.csv", reports)
    rows = {r["domain"]: r["status"] for r in csv.DictReader(path.open(encoding="utf-8"))}
    assert rows == {"radi.rs": "scanned", "ugasen.rs": "unreachable", "zatvoren.rs": "failed"}
