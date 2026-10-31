"""SSRF protection (ADR-006): the scanner does not open private addresses, neither after DNS nor
after a redirect. The local server is on 127.0.0.1, so it is allowed only when a test asks for it.
"""

from __future__ import annotations

import asyncio
import socket

import pytest
from localserver import FakeSite, Response, html

from sitetriage.config import load_config
from sitetriage.fetch import http
from sitetriage.fetch.http import Fetcher, fetch_site
from sitetriage.models import DomainInput
from sitetriage.score import analyze


# --------------------------------------------------------------------------- #
# Level 1 against the local server
# --------------------------------------------------------------------------- #
def _scan(domain: str, config: dict | None = None):
    cfg = config or load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=domain))

    return asyncio.run(run())


def test_local_server_without_permission_gets_no_request():
    with FakeSite(dozvoljen=False) as site:
        snapshot = _scan(site.base_url)
    assert site.requests == []
    assert snapshot.entry.error_kind == "blocked"


def test_explicit_permission_opens_exactly_that_host_and_port():
    with FakeSite(dozvoljen=False) as site:
        cfg = load_config()
        host, port = site.address
        cfg["net"]["allowed_private"] = [f"{host}:{port}"]
        snapshot = _scan(site.base_url, cfg)
    assert snapshot.entry.status == 200 and site.requests


def test_redirect_to_private_address_is_refused():
    """An allowed server redirects to another port; the check runs when every connection is opened."""
    with FakeSite(dozvoljen=False) as target:
        redirect = Response(b"", status=302, headers={"location": f"{target.base_url}/"})
        with FakeSite(extra={"/": redirect}) as site:
            snapshot = _scan(site.base_url)
    assert target.requests == [], "the redirect target must not get a single request"
    assert snapshot.entry.error_kind == "blocked"
    assert "127.0.0.1 → 127.0.0.1" in snapshot.entry.error_detail


def test_name_that_resolves_to_private_address_is_refused(monkeypatch):
    resolved = []

    async def fake_dns(host, port):
        resolved.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(http, "_resolve", fake_dns)
    snapshot = _scan("privatno.test")
    assert resolved and set(resolved) == {"privatno.test"}
    assert snapshot.entry.error_kind == "blocked"
    assert snapshot.entry.error_detail == "address is not public: privatno.test → 10.0.0.5"
    assert snapshot.pages == [], "after a block there is neither robots.txt nor a sitemap"


def test_refused_connection_on_allowed_address_is_not_a_block():
    """An allowed address where nobody listens is an ordinary network error, not the protection."""
    cfg = load_config()
    cfg["net"]["allowed_private"] = ["127.0.0.1:1"]
    snapshot = _scan("http://127.0.0.1:1", cfg)
    assert snapshot.entry.error_kind == "no_connection"


def test_protection_does_not_vanish_silently_when_httpx_changes(monkeypatch):
    """The backend is installed through an internal httpx field; without it the tool refuses to run."""
    import types

    import httpx

    class WithoutBackend(httpx.AsyncHTTPTransport):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._pool = types.SimpleNamespace()

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", WithoutBackend)
    with pytest.raises(RuntimeError, match="SSRF"):
        Fetcher(load_config())._make_client(verify=True)


def test_name_without_dns_records_stays_a_dns_error(monkeypatch):
    async def no_records(host, port):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(http, "_resolve", no_records)
    assert _scan("nepostoji.test").entry.error_kind == "dns_nxdomain"


def test_blocked_domain_is_not_unreachable():
    """The site may work; we just chose not to open it. That is `failed`, not "unreachable"."""
    with FakeSite(dozvoljen=False) as site:
        snapshot = _scan(site.base_url)
    report = analyze(snapshot, load_config())
    assert report.status == "failed"
    assert snapshot.entry.error_kind == "blocked"


def test_input_with_ip_address_sends_no_request():
    with FakeSite(dozvoljen=False) as site:
        _, port = site.address
        snapshot = _scan(f"127.0.0.1:{port}")
    assert site.requests == []
    assert snapshot.entry.error_kind == "blocked" and "with a port" in snapshot.entry.error_detail


# --------------------------------------------------------------------------- #
# Level 2: the log says why a request was refused. Chromium reports the same for both
# cases, ERR_BLOCKED_BY_CLIENT, and a failed DNS lookup is not a private address.
# --------------------------------------------------------------------------- #
class FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = type("Request", (), {"url": url})()
        self.outcome: str | None = None

    async def continue_(self) -> None:
        self.outcome = "continue"

    async def abort(self, code: str) -> None:
        self.outcome = code


NO_DNS = "DNS did not resolve the name"


@pytest.mark.parametrize(
    "resolution, reason",
    [
        pytest.param(socket.gaierror(socket.EAI_AGAIN, "temporary"), NO_DNS, id="ke-dns"),
        # A name that does not exist is not retried: the DNS answer is final.
        pytest.param(socket.gaierror(socket.EAI_NONAME, "none"), NO_DNS, id="ke-no-name"),
        pytest.param(
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))],
            "address is not public: 10.0.0.5",
            id="ke-private",
        ),
    ],
)
def test_level_2_logs_why_it_refuses_a_request(monkeypatch, caplog, resolution, reason):
    from sitetriage.fetch.browser import _address_guard

    def fake_dns(*_args, **_kwargs):
        if isinstance(resolution, Exception):
            raise resolution
        return resolution

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    route = FakeRoute("https://primer.rs/")
    caplog.set_level("INFO", logger="sitetriage")
    asyncio.run(_address_guard(frozenset(), RuntimeError, "primer.rs")(route))
    assert route.outcome == "blockedbyclient"
    [record] = [r for r in caplog.records if "refuses" in r.getMessage()]
    assert reason in record.getMessage() and "primer.rs:443" in record.getMessage()
    assert record.domain == "primer.rs"


def test_level_2_retries_a_temporary_dns_error(monkeypatch):
    """The verdict holds for the whole domain, so one temporary error would block all requests to the host."""
    from sitetriage.fetch.browser import _address_guard

    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))]
    answers = [socket.gaierror(socket.EAI_AGAIN, "temporary"), public]

    def fake_dns(*_args, **_kwargs):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    route = FakeRoute("https://primer.rs/")
    asyncio.run(_address_guard(frozenset(), RuntimeError, "primer.rs")(route))
    assert route.outcome == "continue" and not answers


# --------------------------------------------------------------------------- #
# Level 2: `route` checks every browser request
# --------------------------------------------------------------------------- #
def _level2(site: FakeSite):
    from sitetriage.fetch.browser import capture_all
    from sitetriage.models import Entry, PageSnapshot, SiteSnapshot

    snapshot = SiteSnapshot(
        domain=site.base_url,
        pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        entry=Entry(requested_url=site.base_url + "/", final_url=site.base_url + "/", status=200),
    )
    return asyncio.run(capture_all([snapshot], load_config()))[site.base_url]


@pytest.mark.browser
def test_browser_does_not_load_resource_from_private_address():
    with FakeSite(dozvoljen=False) as private:
        page = html("Strana", body=f"<img src='{private.base_url}/slika.png'>")
        with FakeSite(extra={"/": Response(page)}) as site:
            snapshot = _level2(site)
    assert snapshot.status == "ok", snapshot.errors
    assert private.requests == [], "the browser must not fetch a resource from a private address"


@pytest.mark.browser
def test_browser_does_not_open_page_on_private_address():
    with FakeSite(dozvoljen=False) as private:
        snapshot = _level2(private)
    assert snapshot.status == "failed" and snapshot.errors[0].stage == "goto"
    assert private.requests == []


@pytest.mark.browser
@pytest.mark.xfail(
    strict=True,
    reason="ADR-006: Playwright `route` does not see the redirect target; an egress filter covers it",
)
def test_browser_does_not_follow_redirect_to_private_address():
    """A known limitation of level 2. When Playwright starts seeing redirects, the test passes and
    `strict` fails it, so the limitation is removed from ADR-006."""
    with FakeSite(dozvoljen=False) as target:
        redirect = Response(b"", status=302, headers={"location": f"{target.base_url}/"})
        with FakeSite(extra={"/": redirect}) as site:
            _level2(site)
    assert target.requests == []
