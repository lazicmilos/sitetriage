"""ADR-014: the same site at four URLs (http/https × www/without www).

The fake site is a table: origin → what the home page returns. The other paths (robots, sitemaps,
probes) return 404.
"""

from __future__ import annotations

import asyncio

import pytest
from factories import clean_site, run_level
from localserver import html

from sitetriage.config import load_config
from sitetriage.fetch.http import Fetcher, Outcome, fetch_site
from sitetriage.messages import render
from sitetriage.models import DomainInput, HostVariant

DOMAIN = "primer.rs"
BARE, WWW = f"https://{DOMAIN}", f"https://www.{DOMAIN}"
HTTP_BARE, HTTP_WWW = f"http://{DOMAIN}", f"http://www.{DOMAIN}"
ERRORS = {
    "connection": ("no_connection", "refused"),
    "dns": ("dns_nxdomain", "Name or service not known"),
    "certificate": ("tls", "certificate has expired"),
    "dns_temporary": ("dns_temporary", "[Errno -3] Temporary failure in name resolution"),
}
MISSING = "infra.https.redirect.missing"
DUPLICATE = "infra.host.duplicate"


class Site(Fetcher):
    """`behaviour[origin]`: "200", the origin it redirects to, or an error from `ERRORS`.

    An origin missing from the table has no DNS record. A certificate with an error passes when it is
    not verified. `served` are the URLs that returned a page; a redirect to `stop_at` is not followed.
    """

    def __init__(self, cfg: dict, behaviour: dict[str, str], canonical: dict[str, str] | None = None) -> None:
        super().__init__(cfg)
        self.behaviour = behaviour
        self.canonical = canonical or {}
        self.sent: list[str] = []
        self.served: list[str] = []

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        self.sent.append(url)
        chain = [url]
        while True:
            scheme, _, rest = url.partition("://")
            origin = f"{scheme}://{rest.split('/')[0]}"
            outcome = self.behaviour.get(origin, "dns")
            if outcome == "certificate" and not verify:
                outcome = "200"
            if outcome in ERRORS:
                return Outcome(url=chain[0], error_kind=ERRORS[outcome][0], error_detail=ERRORS[outcome][1])
            if outcome == "200":
                break
            url = outcome + url.removeprefix(origin)
            chain.append(url)
            if url == stop_at:
                return Outcome(url=chain[0], status=301, final_url=url, redirect_chain=chain)
        if url != f"{origin}/":
            return Outcome(url=chain[0], status=404, final_url=url, redirect_chain=chain, body=b"")
        self.served.append(url)
        canonical = self.canonical.get(origin)
        head = f'<link rel="canonical" href="{canonical}">' if canonical else ""
        return Outcome(
            url=chain[0], status=200, final_url=url, redirect_chain=chain, body=html("Početna", head=head)
        )


def scan(monkeypatch, behaviour: dict[str, str], *, canonical=None, budget: int | None = None):
    monkeypatch.setattr("sitetriage.fetch.http.random.uniform", lambda *_: 0)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    if budget is not None:
        cfg["http"]["max_requests_per_domain"] = budget
    fetcher = Site(cfg, behaviour, canonical)

    async def run():
        async with fetcher:
            return await fetch_site(fetcher, DomainInput(domain=DOMAIN))

    return asyncio.run(run()), fetcher


def site(https: bool, redirects: bool, www: bool) -> dict[str, str]:
    behaviour = {BARE: "200" if https else "connection", HTTP_BARE: BARE if redirects else "200"}
    if www:
        behaviour |= {WWW: "200" if https else "connection", HTTP_WWW: WWW if redirects else "200"}
    return behaviour


def _tab(https, redirects, www, missing, duplicate):
    name = "-".join(
        [
            "tab",
            "https-works" if https else "https-unreachable",
            "http-redirects" if redirects else "http-no-redirect",
            "www-exists" if www else "www-missing",
        ]
    )
    return pytest.param(site(https, redirects, www), missing, duplicate, id=name)


@pytest.mark.parametrize(
    "behaviour, missing, duplicate",
    [
        _tab(True, True, False, "ok", "ok"),
        _tab(True, True, True, "ok", "finding"),
        _tab(True, False, False, "finding", "ok"),
        _tab(True, False, True, "finding", "finding"),
        # http redirects to an https that does not work: the site does not open, so there is no claim.
        _tab(False, True, False, "unknown", "unknown"),
        _tab(False, True, True, "unknown", "unknown"),
        # Only http: there is no https to redirect to.
        _tab(False, False, False, "not_applicable", "ok"),
        _tab(False, False, True, "not_applicable", "finding"),
    ],
)
def test_four_variants(monkeypatch, behaviour, missing, duplicate):
    snapshot, _ = scan(monkeypatch, behaviour)
    results = run_level(1, snapshot)
    assert (results[MISSING].status, results[DUPLICATE].status) == (missing, duplicate)


def test_duplicate_evidence_is_the_hosts(monkeypatch):
    snapshot, _ = scan(monkeypatch, site(True, True, True))
    [finding] = run_level(1, snapshot)[DUPLICATE].findings
    assert finding.evidence["hosts"] == [DOMAIN, f"www.{DOMAIN}"]


def test_host_count_in_sentence_matches_the_list(monkeypatch):
    """BUG-017: http without a redirect went into the list, so "2 adrese" stood next to four hosts."""
    snapshot, _ = scan(monkeypatch, site(True, False, True))
    [finding] = run_level(1, snapshot)[DUPLICATE].findings
    assert f"na 2 adrese ({DOMAIN}, www.{DOMAIN})" in render(finding, "sr").client


def test_https_is_checked_on_the_host_the_home_page_lands_on(monkeypatch):
    """The home page redirects to www, and http without www does not: a duplicate, not a missing redirect."""
    snapshot, _ = scan(monkeypatch, {BARE: WWW, WWW: "200", HTTP_BARE: "200", HTTP_WWW: WWW})
    results = run_level(1, snapshot)
    assert (results[MISSING].status, results[DUPLICATE].status) == ("ok", "finding")


def test_variants_are_in_the_snapshot_with_their_chain(monkeypatch):
    """The other three variants of the final origin, each with status, final URL and chain."""
    snapshot, _ = scan(monkeypatch, site(True, True, True))
    variants = {v.url: v for v in snapshot.host_variants}
    assert set(variants) == {f"{WWW}/", f"{HTTP_BARE}/", f"{HTTP_WWW}/"}
    assert variants[f"{HTTP_WWW}/"].redirect_chain == [f"{HTTP_WWW}/", f"{WWW}/"]
    assert variants[f"{HTTP_WWW}/"].status == 200


def test_variant_leading_to_the_home_page_does_not_request_it_again(monkeypatch):
    """The home page is downloaded once; a variant that leads to it gets its status and canonical."""
    snapshot, fetcher = scan(monkeypatch, site(True, True, False), canonical={BARE: f"{BARE}/"})
    assert fetcher.served.count(f"{BARE}/") == 1
    [http] = [v for v in snapshot.host_variants if v.url == f"{HTTP_BARE}/"]
    expected = (200, f"{BARE}/", [f"{HTTP_BARE}/", f"{BARE}/"])
    assert (http.status, http.canonical, http.redirect_chain) == expected


def test_variants_come_before_the_sitemap_in_the_budget(monkeypatch):
    """Home page 1 + robots 1 + variants 3: a budget of five requests does not reach the sitemap."""
    snapshot, fetcher = scan(monkeypatch, site(True, True, False), budget=5)
    assert fetcher.sent[:2] == [f"{BARE}/", f"{BARE}/robots.txt"]
    assert sorted(fetcher.sent[2:]) == sorted(v.url for v in snapshot.host_variants)
    assert len(snapshot.host_variants) == 3
    assert all(v.error_kind != "budget" for v in snapshot.host_variants)
    assert snapshot.sitemap.status is None


@pytest.mark.parametrize(
    "behaviour, missing, duplicate",
    [
        pytest.param(
            {BARE: "200", HTTP_BARE: BARE, WWW: "certificate", HTTP_WWW: WWW},
            "ok",
            "unknown",
            id="www-with-bad-certificate",
        ),
        pytest.param(
            {BARE: "certificate", HTTP_BARE: "200"}, "unknown", "ok", id="bad-certificate-on-final-host"
        ),
    ],
)
def test_variant_with_tls_error_is_unknown(monkeypatch, behaviour, missing, duplicate):
    snapshot, _ = scan(monkeypatch, behaviour)
    results = run_level(1, snapshot)
    assert (results[MISSING].status, results[DUPLICATE].status) == (missing, duplicate)
    if WWW in behaviour:
        [bad] = [v for v in snapshot.host_variants if v.url == f"{WWW}/"]
        assert bad.error_kind == "tls" and "expired" in bad.error_detail


def test_variant_with_temporary_dns_error_is_unknown(monkeypatch):
    """A temporary DNS error does not say the host is missing, so whether it serves the site is unknown."""
    snapshot, _ = scan(monkeypatch, {BARE: "200", HTTP_BARE: BARE, WWW: "dns_temporary", HTTP_WWW: WWW})
    assert run_level(1, snapshot)[DUPLICATE].status == "unknown"


@pytest.mark.parametrize("canonical, severity", [(f"{BARE}/", "low"), (None, "medium")])
def test_canonical_on_all_variants_lowers_to_low(canonical, severity):
    site = clean_site(domain=DOMAIN)
    site.home.canonical_normalized = canonical
    www = HostVariant(url=f"{HTTP_WWW}/", status=200, final_url=f"{HTTP_WWW}/", canonical=canonical)
    site.host_variants = [www]
    result = run_level(1, site)[DUPLICATE]
    assert result.status == "finding" and result.findings[0].severity == severity


def test_without_recorded_variants_is_unknown():
    site = clean_site()
    site.host_variants = None
    results = run_level(1, site)
    assert results[MISSING].status == results[DUPLICATE].status == "unknown"
