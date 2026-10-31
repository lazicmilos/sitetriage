"""Integration tests of the level 1 fetcher against a local server.

No outside network, but with real `httpx`, real semaphores and a real budget: only that way
are the request budget, the retry rules and the politeness rules really checked.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import replace

import httpx
import pytest
from factories import run_level
from localserver import FakeSite, Response, html

from sitetriage import store
from sitetriage.config import load_config
from sitetriage.fetch.http import (
    DomainBudget,
    Fetcher,
    Outcome,
    _classify,
    _should_retry,
    fetch_site,
    probe_urls,
    scan_domains,
)
from sitetriage.messages import render
from sitetriage.models import DomainInput


def scan(site: FakeSite, **config_overrides) -> object:
    """Delays are zero by default; the politeness test turns them on explicitly."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    for dotted, value in config_overrides.items():
        section, _, key = dotted.rpartition(".")
        node = cfg
        for part in section.split("."):
            node = node[part]
        node[key] = value

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=site.base_url, industry="other"))

    return asyncio.run(run())


# --------------------------------------------------------------------------- #
# Full run
# --------------------------------------------------------------------------- #
def test_full_run_assembles_the_snapshot():
    with FakeSite() as site:
        snapshot = scan(site)

    assert snapshot.entry.status == 200
    assert snapshot.robots.status == 200
    assert snapshot.sitemap.status == 200
    assert snapshot.sample_source == "sitemap"
    assert snapshot.home.title == "Početna"
    assert snapshot.home.raw_html, "the raw HTML of the home page is needed for escalation and debugging"
    assert all(p.raw_html is None for p in snapshot.pages[1:]), "raw HTML only for the home page"
    assert len(snapshot.pages) >= 4
    assert len(snapshot.soft404.probes) == 2
    assert all(p.status == 404 for p in snapshot.soft404.probes)


def test_every_request_has_a_debug_record_for_its_domain(caplog):
    """`--debug-domain` filters by the `domain` field, so each request must carry it (BUG-11)."""
    import logging

    caplog.set_level(logging.DEBUG, logger="sitetriage")
    with FakeSite() as site:
        snapshot = scan(site)
    records = [r for r in caplog.records if r.levelno == logging.DEBUG and r.name == "sitetriage.fetch"]
    assert len(records) == snapshot.budget.requests_made, "one record per request"
    assert {r.domain for r in records} == {site.base_url}
    home = next(r.getMessage() for r in records if r.getMessage().startswith(f"GET {site.base_url}/ "))
    assert "status 200" in home and " ms" in home and "hops" in home and "truncated" in home
    probe = next(r.getMessage() for r in records if "/robots.txt" in r.getMessage())
    assert "status 200" in probe


def test_a_failed_request_logs_its_error_kind(caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="sitetriage")

    class TimesOut(Fetcher):
        async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
            return Outcome(url=url, error_kind="timeout", error_detail="slow")

    async def run():
        async with TimesOut(load_config()) as fetcher:
            budget = DomainBudget(5, 30, domain="nema.test")
            return await fetcher.request("https://nema.test/", budget, retries=0)

    asyncio.run(run())
    [record] = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert record.domain == "nema.test" and "error timeout" in record.getMessage()


def test_home_page_redirecting_by_script_is_a_hop_like_an_http_redirect():
    """BUG-022: a 95 B stub that leads to /uskoro/ with JavaScript was scored as the home page."""
    stub = b"<html><head><script>location.replace('/uskoro/')</script></head><body></body></html>"
    coming_soon = Response(html("Uskoro", body="<h1>Uskoro</h1>"))
    with FakeSite(extra={"/": Response(stub), "/uskoro/": coming_soon}) as site:
        snapshot = scan(site)

    assert snapshot.home.title == "Uskoro"
    assert snapshot.home.final_url == f"{site.base_url}/uskoro/"
    assert snapshot.entry.redirect_chain == [f"{site.base_url}/", f"{site.base_url}/uskoro/"]
    assert snapshot.home.redirect_hops == 1
    assert run_level(1, snapshot)["seo.title.missing"].status == "ok"


def test_clean_local_site_gives_few_findings():
    """The guard against false positives on a deliberately tidy site (success criterion U4)."""
    with FakeSite() as site:
        snapshot = scan(site)
    findings = {cid for cid, r in run_level(1, snapshot).items() if r.status == "finding"}
    assert findings <= {"infra.sitemap.missing"} or findings == set(), f"unexpected findings: {findings}"


def test_recursion_through_sitemapindex():
    with FakeSite() as site:
        snapshot = scan(site)
    assert snapshot.sitemap.nested_count == 1
    assert snapshot.sitemap.depth_reached == 1
    assert any(url.endswith("/usluge") for url in snapshot.sitemap.urls)


def test_sitemaps_of_other_domains_in_robots_do_not_use_up_the_file_limit():
    """BUG-027: the robots.txt of a chain lists the sitemaps of all its sites.

    This site has an index with a nested sitemap.
    """
    foreign = "".join(f"Sitemap: https://lanac-{i}.test/sitemap.xml\n" for i in range(3))

    def robots():
        return Response(f"User-agent: *\nSitemap: {site.base_url}/sitemap.xml\n{foreign}".encode())

    with FakeSite(extra={"/robots.txt": robots}) as site:
        snapshot = scan(site)
    assert any(url.endswith("/usluge") for url in snapshot.sitemap.urls)


def test_robots_disallow_is_obeyed():
    """The sitemap offers /tajno/nesto; a tool that requests it anyway is inconsistent."""
    with FakeSite() as site:
        snapshot = scan(site)
        requested = site.paths()
    assert any("/tajno/nesto" in url for url in snapshot.sitemap.urls), "the sitemap did offer it"
    assert not any(path.startswith("/tajno") for path in requested), f"requested paths: {requested}"


def test_sitemap_directive_from_robots_wins():
    with FakeSite() as site:
        scan(site)
        requested = site.paths()
    assert "/sitemap.xml" in requested


def test_probes_are_deterministic():
    """The same domain must give the same soft-404 probes in every run, or the tests mean nothing."""
    first = probe_urls("institucija.example", "https://institucija.example/")
    assert first == probe_urls("institucija.example", "https://institucija.example/")
    assert first != probe_urls("restoran-ugao.example", "https://restoran-ugao.example/")
    assert first[0].endswith("e3ce7e80ecbd5228") and first[1].endswith(".html")


def test_probes_in_snapshot_follow_the_pure_function():
    with FakeSite() as site:
        snapshot = scan(site)
        expected = probe_urls(site.base_url, site.base_url)
    assert [p.url for p in snapshot.soft404.probes] == expected


# --------------------------------------------------------------------------- #
# Politeness and concurrency
# --------------------------------------------------------------------------- #
def test_never_two_parallel_requests_to_the_same_host():
    """The per-host semaphore is the line between a tool and an attack."""
    with FakeSite() as site:
        scan(site)
        assert site.concurrent_peak == 1, f"parallel requests to the same host: {site.concurrent_peak}"


def test_delay_between_requests_to_the_same_host():
    with FakeSite() as site:
        import time

        started = time.monotonic()
        scan(site, **{"http.delay_ms": [120, 120], "http.max_requests_per_domain": 5})
        elapsed = time.monotonic() - started
    assert elapsed >= 0.4, f"delays were not respected, the run took {elapsed:.2f} s"


def test_www_and_bare_host_share_the_politeness_key():
    """Two requests to `www.x.rs` and `x.rs` go one after the other, with a delay between them."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [100, 100]
    in_parallel, peak, starts = 0, 0, []

    class Slow(Fetcher):
        async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
            nonlocal in_parallel, peak
            in_parallel += 1
            peak = max(peak, in_parallel)
            starts.append(time.monotonic())
            await asyncio.sleep(0.05)
            in_parallel -= 1
            return Outcome(url=url, status=200, final_url=url)

    async def run():
        async with Slow(cfg) as fetcher:
            budget = DomainBudget(10, 30)
            www, bare = "https://www.primer.rs/", "https://primer.rs/"
            await asyncio.gather(fetcher.request(www, budget), fetcher.request(bare, budget))

    asyncio.run(run())
    assert peak == 1
    assert starts[1] - starts[0] >= 0.1, "the second request also waits for the politeness delay"


def test_several_domains_run_in_parallel():
    with FakeSite() as a, FakeSite() as b, FakeSite() as c:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        targets = [DomainInput(domain=s.base_url) for s in (a, b, c)]
        snapshots = asyncio.run(scan_domains(targets, cfg))
    assert len(snapshots) == 3
    assert all(s.entry.status == 200 for s in snapshots)


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
def test_budget_stops_the_run_without_crashing_it():
    with FakeSite() as site:
        snapshot = scan(site, **{"http.max_requests_per_domain": 3, "http.delay_ms": [0, 0]})
        requested = len(site.paths())

    assert requested <= 3, f"budget exceeded: {requested} requests"
    assert snapshot.budget.exhausted
    assert "budget" in snapshot.budget.aborted_reason
    # What was collected goes on, the rest is `unknown`, not a crash.
    assert snapshot.entry.status == 200
    results = run_level(1, snapshot)
    assert len(results) == 22
    assert all(r.reason for r in results.values() if r.status == "unknown")


def test_budget_also_counts_time():
    budget = DomainBudget(max_requests=100, max_seconds=0)
    assert budget.take() is False
    assert "s" in budget.aborted_reason


# --------------------------------------------------------------------------- #
# Errors, retries, giving up
# --------------------------------------------------------------------------- #
def test_500_is_retried_once_and_succeeds():
    attempts = {"count": 0}

    def flaky() -> Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return Response(b"error", status=500)
        return Response(html("Usluge"))

    with FakeSite(extra={"/usluge": flaky}) as site:
        snapshot = scan(site)

    services = [p for p in snapshot.pages if p.url.endswith("/usluge")]
    assert attempts["count"] == 2, "5xx is retried exactly once"
    assert services and services[0].status == 200


def test_400_is_not_retried():
    attempts = {"count": 0}

    def not_found() -> Response:
        attempts["count"] += 1
        return Response(b"none", status=404)

    with FakeSite(extra={"/usluge": not_found}) as site:
        scan(site)
    assert attempts["count"] == 1, "4xx is an answer, not an error"


def test_on_429_the_domain_is_given_up():
    with FakeSite(extra={"/robots.txt": Response(b"stop", status=429)}) as site:
        snapshot = scan(site)
        requested = site.paths()

    assert "429" in snapshot.budget.aborted_reason
    assert requested.count("/robots.txt") == 1, "429 is not retried"
    assert len(requested) == 2, f"no further requests after 429, but there were: {requested}"


def test_soft_404_is_recognized_through_the_whole_chain():
    with FakeSite(soft404=True) as site:
        snapshot = scan(site)

    assert all(p.status == 200 for p in snapshot.soft404.probes)
    result = run_level(1, snapshot)["infra.soft404"]
    assert result.status == "finding"
    assert result.findings[0].evidence["hard_evidence"] is True


def test_redirects_are_recorded():
    with FakeSite(
        extra={
            "/": Response(b"", status=301, headers={"Location": "/korak1"}),
            "/korak1": Response(b"", status=301, headers={"Location": "/korak2"}),
            "/korak2": Response(b"", status=301, headers={"Location": "/kraj"}),
            "/kraj": Response(html("Kraj")),
        }
    ) as site:
        snapshot = scan(site)

    assert snapshot.entry.status == 200
    assert len(snapshot.entry.redirect_chain) == 4
    assert run_level(1, snapshot)["perf.redirect.chain"].status == "finding"


@pytest.mark.parametrize(
    "stop_at, requested, status", [("/", ["/stara", "/nova"], 302), ("/drugde", None, 200)]
)
def test_redirect_to_already_downloaded_url_is_not_followed(stop_at, requested, status):
    """A host variant stops before the already downloaded home page; otherwise it goes on (ADR-014)."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    with FakeSite(
        extra={
            "/stara": Response(b"", status=301, headers={"Location": "/nova"}),
            "/nova": Response(b"", status=302, headers={"Location": "/"}),
        }
    ) as site:
        b = site.base_url

        async def run():
            async with Fetcher(cfg) as fetcher:
                return await fetcher.request(f"{b}/stara", DomainBudget(5, 30), stop_at=f"{b}{stop_at}")

        outcome = asyncio.run(run())
        assert site.paths() == (requested or ["/stara", "/nova", "/"])
    assert (outcome.status, outcome.final_url) == (status, f"{b}/")
    assert outcome.redirect_chain == [f"{b}/stara", f"{b}/nova", f"{b}/"]


def link_measurement(site: FakeSite, path: str, max_s: float = 5):
    from sitetriage.fetch.http import measure_link

    cfg = load_config()
    cfg["network_profile"] |= {"probe_url": f"{site.base_url}{path}", "probe_max_s": max_s}
    return asyncio.run(measure_link(cfg))


def test_link_measurement_gives_a_speed():
    """ADR-018: the local server is faster than any real link."""
    with FakeSite(extra={"/proba.bin": Response(b"x" * 2_000_000)}) as site:
        assert link_measurement(site, "/proba.bin") > 50


def test_link_measurement_has_a_hard_deadline():
    """On a slow link, what arrives within `probe_max_s` is measured; the whole file is not waited for."""
    with FakeSite(extra={"/proba.bin": Response(b"x" * 2_000_000, stall=10)}) as site:
        started = time.monotonic()
        speed = link_measurement(site, "/proba.bin", max_s=1)
        assert time.monotonic() - started < 4
    assert speed is not None and speed < 1


@pytest.mark.parametrize(
    "response", [None, Response(b"x", delay=3)], ids=["no-file", "no-byte-before-deadline"]
)
def test_failed_link_measurement_is_none(response):
    with FakeSite(extra={"/proba.bin": response} if response else {}) as site:
        assert link_measurement(site, "/proba.bin", max_s=1) is None


def test_compressed_response_does_not_fire_a_finding():
    with FakeSite(
        extra={"/": Response(html("Početna", body="x" * 80_000), headers={"content-encoding": "gzip"})}
    ) as site:
        snapshot = scan(site)
    assert snapshot.home.headers.get("content-encoding") == "gzip"
    assert run_level(1, snapshot)["perf.compression.missing"].status == "ok"


def test_uncompressed_large_html_fires_a_finding():
    with FakeSite(extra={"/": Response(html("Početna", body="x" * 80_000))}) as site:
        snapshot = scan(site)
    assert run_level(1, snapshot)["perf.compression.missing"].status == "finding"


def test_fallback_to_internal_links_without_a_sitemap():
    with FakeSite(
        extra={
            "/sitemap.xml": Response(b"none", status=404),
            "/robots.txt": Response(b"none", status=404),
        }
    ) as site:
        snapshot = scan(site)

    assert snapshot.sample_source == "links"
    assert any(p.url.endswith("/usluge") for p in snapshot.pages)
    assert run_level(1, snapshot)["infra.sitemap.missing"].status == "finding"
    assert run_level(1, snapshot)["infra.robots.missing"].status == "finding"


# --------------------------------------------------------------------------- #
# Exception classification: the only part of the retry rules that cannot be provoked locally
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc, expected",
    [
        (httpx.ConnectError("x", request=None), "connection"),
        (httpx.ConnectTimeout("x", request=None), "connect_timeout"),
        (httpx.ReadTimeout("x", request=None), "read_timeout"),
        (httpx.TooManyRedirects("x", request=None), "too_many_redirects"),
    ],
)
def test_exception_classification(exc, expected):
    assert _classify(exc)[0] == expected


def test_dns_error_is_recognized_through_the_cause_chain():
    try:
        try:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        except socket.gaierror as cause:
            raise httpx.ConnectError("error", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "dns_nxdomain"


def test_expired_certificate_is_tls_not_a_crash():
    import ssl

    try:
        try:
            raise ssl.SSLCertVerificationError("certificate has expired")
        except ssl.SSLCertVerificationError as cause:
            raise httpx.ConnectError("error", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "tls"


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (Outcome(url="u", status=404), False),
        (Outcome(url="u", status=500), True),
        (Outcome(url="u", status=200), False),
        (Outcome(url="u", error_kind="read_timeout"), True),
        (Outcome(url="u", error_kind="dns"), False),
        (Outcome(url="u", error_kind="dns_nxdomain"), False),
        # EAI_AGAIN is temporary by definition: a hotspot gave it for every fourth domain (run F on list A)
        (Outcome(url="u", error_kind="dns_temporary"), True),
        (Outcome(url="u", error_kind="tls"), False),
    ],
)
def test_retry_policy(outcome, expected):
    assert _should_retry(outcome) is expected


def test_broken_domain_does_not_crash_the_run():
    """Adding a deliberately broken domain must not bring down the whole run."""
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        cfg["http"]["timeout_connect_s"] = 1
        targets = [
            DomainInput(domain=site.base_url),
            DomainInput(domain="http://127.0.0.1:1"),  # nobody listens
        ]
        snapshots = asyncio.run(scan_domains(targets, cfg))

    assert len(snapshots) == 2
    assert snapshots[0].entry.status == 200
    assert snapshots[1].entry.status is None
    assert run_level(1, snapshots[1]) and len(run_level(1, snapshots[1])) == 22


def test_snapshot_is_written_to_disk_as_soon_as_the_domain_is_done(tmp_path):
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        asyncio.run(scan_domains([DomainInput(domain=site.base_url)], cfg, snapshot_dir=tmp_path))

    written = list(tmp_path.glob("*/site.json"))
    assert len(written) == 1, f"not written: {list(tmp_path.rglob('*'))}"
    loaded = list(store.read_all(tmp_path))
    assert len(loaded) == 1 and loaded[0][0].entry.status == 200


@pytest.mark.parametrize(
    "domain, expected",
    [
        ("institucija.example", "institucija.example"),
        ("http://127.0.0.1:8123", "http_127.0.0.1_8123~"),
        ("../../etc/passwd", "etc_passwd~"),
        ("", "unknown-domain~"),
    ],
)
def test_directory_name_does_not_leave_the_output_directory(domain, expected):
    """The domain comes from the user's CSV: a trust boundary. A changed name also gets a hash
    suffix after `~`, so two domains never share a folder (BUG-03)."""
    name = store.slug(domain)
    hash_length = 8 if expected.endswith("~") else 0
    assert name.startswith(expected) and len(name) == len(expected) + hash_length
    assert "/" not in name and ".." not in name


# --------------------------------------------------------------------------- #
# Regressions from the review before the first real run: each is silent on localhost and
# loud on 200 real domains.
# --------------------------------------------------------------------------- #
class SlowSite(FakeSite):
    """Every response is delayed; otherwise the local server answers in microseconds."""

    def __init__(self, *, delay: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    def route(self, path: str) -> Response:
        return replace(super().route(path), delay=self.delay)


def test_time_budget_starts_only_when_the_domain_gets_its_turn():
    """The 40 s budget is for work on the domain, not for waiting in the queue behind the other 199.

    Ten domains on two slots = five rounds, so one domain's work is about a fifth of the run.
    If the clock started for all at once, the last domains would have used up almost the whole
    run time. The ratio is compared, not the absolute time, so the test does not depend on the
    speed of the machine.
    """
    import time

    sites = [SlowSite(delay=0.05) for _ in range(10)]
    for site in sites:
        site.__enter__()
    try:
        cfg = load_config()
        cfg["http"].update(delay_ms=[0, 0], concurrency=2, domain_concurrency=2)
        targets = [DomainInput(domain=s.base_url) for s in sites]
        start = time.monotonic()
        snapshots = asyncio.run(scan_domains(targets, cfg))
        total = time.monotonic() - start
    finally:
        for site in sites:
            site.__exit__()

    longest = max(s.budget.elapsed_ms for s in snapshots) / 1000
    assert longest < total * 0.6, (
        f"a domain used {longest:.1f} s of a {total:.1f} s run: the clock ran while it waited in the queue"
    )


def test_response_time_does_not_include_the_politeness_delay():
    """`elapsed_ms` is what the server does, not what we wait for.

    Otherwise the escalation rule "home page answers in > 1500 ms" fires for everyone who
    waited in the queue, and loses the reason it exists for (b2b-firma.example).
    """
    with FakeSite() as site:
        # home page + robots + 2 sitemaps + 2 probes = 6; only the seventh and eighth requests are the sample
        snapshot = scan(site, **{"http.delay_ms": [600, 600], "http.max_requests_per_domain": 8})
    sample = snapshot.pages[1:]
    assert sample, "the sample must have at least one page"
    # The delay is 600 ms; a local response takes about ten ms, and up to ~300 ms under load.
    assert all(p.elapsed_ms < 450 for p in sample), [p.elapsed_ms for p in sample]


class IndexPhpSite(FakeSite):
    """PHP with PATH_INFO: `/index.php/anything` returns 200, while a real 404 works."""

    def route(self, path: str) -> Response:
        if path == "/":
            return Response(b"", status=302, headers={"Location": "/index.php"})
        if path == "/index.php" or path.startswith("/index.php/"):
            return super().route("/")
        return super().route(path)


def test_probes_go_to_the_origin_not_the_home_page_path():
    """A `/index.php/<token>` probe would return 200 on a PHP site → a false `infra.soft404` (high)."""
    with IndexPhpSite() as site:
        snapshot = scan(site)
        expected = probe_urls(site.base_url, site.base_url)

    assert snapshot.home.final_url.endswith("/index.php")
    assert [p.url for p in snapshot.soft404.probes] == expected
    assert run_level(1, snapshot)["infra.soft404"].status == "ok"


class ExpiredCertificate(Fetcher):
    """Without a real TLS server: certificate verification fails, the fetch without verification succeeds."""

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        if verify:
            return Outcome(url=url, error_kind="tls", error_detail="certificate has expired")
        if url.endswith("/"):
            return Outcome(url=url, status=200, final_url=url, redirect_chain=[url], body=html("Početna"))
        return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")


def test_tls_error_stays_in_the_evidence_when_the_retry_succeeds():
    """An expired certificate is the strongest finding for a sale; without its reason it is just "unknown"."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with ExpiredCertificate(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain="istekao.test"))

    snapshot = asyncio.run(run())
    assert snapshot.entry.status == 200
    assert snapshot.entry.tls.valid is False
    assert snapshot.entry.tls.error == "certificate has expired"
    result = run_level(1, snapshot)["infra.tls.invalid"]
    assert result.status == "finding"
    assert "certificate has expired" in render(result.findings[0]).tech


class YoastSite(FakeSite):
    """WordPress + Yoast: an index with nine sitemaps, each with a few pages.

    Recorded on prodavnica.example (9 sitemaps) and b2b-firma.example (6): reading every sitemap
    used up the budget of 16 requests before the soft-404 probes got their turn (BUG-001).
    """

    SITEMAPS = 9

    def route(self, path: str) -> Response:
        base = self.base_url
        if path == "/robots.txt":
            return Response(f"User-agent: *\nSitemap: {base}/sitemap_index.xml\n".encode())
        if path == "/sitemap_index.xml":
            sitemaps = "".join(
                f"<sitemap><loc>{base}/mapa-{i}.xml</loc></sitemap>" for i in range(self.SITEMAPS)
            )
            return Response(f"<sitemapindex>{sitemaps}</sitemapindex>".encode())
        if path.startswith("/mapa-"):
            i = path.removeprefix("/mapa-").removesuffix(".xml")
            urls = "".join(f"<url><loc>{base}/grupa-{i}/strana-{j}</loc></url>" for j in range(3))
            return Response(f"<urlset>{urls}</urlset>".encode())
        if path.startswith("/grupa-"):
            return Response(html(path))
        return super().route(path)


def test_large_sitemap_does_not_eat_the_soft_404_probes():
    with YoastSite() as site:
        snapshot = scan(site)

    assert snapshot.sitemap.nested_count == YoastSite.SITEMAPS
    assert len(snapshot.soft404.probes) == 2, "the probes were left without budget"
    assert run_level(1, snapshot)["infra.soft404"].status == "ok"
    assert len(snapshot.pages) >= 6, "the sample must still be usable"
    assert not snapshot.budget.exhausted, snapshot.budget.aborted_reason


# --------------------------------------------------------------------------- #
# BUG-004: an interrupted TLS handshake is not an invalid certificate
# --------------------------------------------------------------------------- #
def test_interrupted_handshake_is_not_classified_as_certificate():
    import ssl

    try:
        try:
            raise ssl.SSLEOFError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred")
        except ssl.SSLEOFError as cause:
            raise httpx.ConnectError("error", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "tls_handshake"


class InterruptedHandshake(Fetcher):
    """Recorded: the server drops the handshake with a Python client, and works over http."""

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        if url.startswith("https://"):
            return Outcome(
                url=url, error_kind="tls_handshake", error_detail="[SSL: UNEXPECTED_EOF_WHILE_READING]"
            )
        if url.endswith("/"):
            return Outcome(url=url, status=200, final_url=url, redirect_chain=[url], body=html("Početna"))
        return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")


def test_interrupted_handshake_falls_back_to_http_and_the_certificate_stays_unchecked():
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with InterruptedHandshake(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain="rukovanje.test"))

    snapshot = asyncio.run(run())
    assert snapshot.entry.status == 200, "a site that works over http must be scanned"
    assert snapshot.entry.requested_url == "http://rukovanje.test/"
    tls = run_level(1, snapshot)["infra.tls.invalid"]
    assert tls.status == "unknown", "the certificate was not even checked: neither a finding nor `ok`"


# --------------------------------------------------------------------------- #
# BUG-003 through the whole chain: a site behind bot protection
# --------------------------------------------------------------------------- #
CHALLENGE = (
    b"<!DOCTYPE html><html lang='en'><head><title>Checking your browser before accessing. "
    b"Just a moment...</title></head><body></body></html>"
)


class BlockedSite(FakeSite):
    """Every request gets a 403 and a challenge page, like two sites in the run over 100 domains."""

    def route(self, path: str) -> Response:
        return Response(CHALLENGE, status=403)


def test_blocked_site_has_no_finding():
    with BlockedSite() as site:
        snapshot = scan(site)
    findings = {cid for cid, r in run_level(1, snapshot).items() if r.status == "finding"}
    assert findings == set(), f"we know nothing about the site, yet this was reported: {sorted(findings)}"


# --------------------------------------------------------------------------- #
# State transitions of the entry request: https → (certificate → again without verification) |
# (handshake, connection, timeout → http) | (DNS → end). For every transition: which requests
# were sent, what is in the snapshot and what the certificate check says.
# --------------------------------------------------------------------------- #
OK = "ok"
OUTCOMES = {
    OK: None,
    "certificate": ("tls", "certificate has expired"),
    "handshake": ("tls_handshake", "UNEXPECTED_EOF_WHILE_READING"),
    "connection": ("connection", "ConnectError: refused"),
    "timeout": ("connect_timeout", "ConnectTimeout"),
    "dns": ("dns_nxdomain", "Name or service not known"),
}


class OutcomeTable(Fetcher):
    """Answers from a table: (scheme, with certificate verification) → outcome."""

    def __init__(self, cfg, table):
        super().__init__(cfg)
        self.table = table
        self.sent: list[tuple[str, bool]] = []

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        scheme = url.split("://")[0]
        self.sent.append((scheme, verify))
        if not url.endswith("/") or url.count("/") > 3:
            return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")
        error = OUTCOMES[self.table.get((scheme, verify), "connection")]
        if error:
            return Outcome(url=url, error_kind=error[0], error_detail=error[1])
        return Outcome(url=url, status=200, final_url=url, redirect_chain=[url], body=html("Početna"))


@pytest.mark.parametrize(
    "table, entry_scheme, certificate, first_requests",
    [
        pytest.param({("https", True): OK}, "https", "ok", [("https", True)], id="st-https-succeeded"),
        pytest.param(
            {("https", True): "certificate", ("https", False): OK},
            "https", "finding", [("https", True), ("https", False)], id="st-certificate-then-unverified",
        ),
        pytest.param(
            {("https", True): "certificate", ("https", False): "connection"},
            None, "finding", [("https", True), ("https", False)], id="st-certificate-then-nothing",
        ),
        pytest.param(
            {("https", True): "handshake", ("http", True): OK},
            "http", "unknown", [("https", True), ("http", True)], id="st-handshake-then-http",
        ),
        pytest.param(
            {("https", True): "connection", ("http", True): OK},
            "http", "unknown", [("https", True), ("https", True), ("http", True)],
            id="st-connection-then-http",
        ),
        pytest.param(
            {("https", True): "timeout", ("http", True): "timeout"},
            None, "unknown", [("https", True), ("https", True), ("http", True), ("http", True)],
            id="st-timeout-then-timeout",
        ),
        pytest.param({("https", True): "dns"}, None, "unknown", [("https", True)], id="st-dns-end"),
    ],
)
def test_entry_request_state_transitions(monkeypatch, table, entry_scheme, certificate, first_requests):
    # no delay before the retry
    monkeypatch.setattr("sitetriage.fetch.http.random.uniform", lambda *_: 0)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    fetcher = OutcomeTable(cfg, table)

    async def run():
        async with fetcher:
            return await fetch_site(fetcher, DomainInput(domain="stanja.test"))

    snapshot = asyncio.run(run())
    assert fetcher.sent[: len(first_requests)] == first_requests
    if entry_scheme is None:
        assert snapshot.entry.status is None
    else:
        assert snapshot.entry.status == 200 and snapshot.entry.requested_url.startswith(f"{entry_scheme}://")
    results = run_level(1, snapshot)
    assert results["infra.tls.invalid"].status == certificate
    if table.get(("https", True)) == "dns":
        assert len(fetcher.sent) == 1, "no other requests after a DNS error"
        # Only the second attempt, run by `scan_domains`, proves the site is unreachable (ADR-013).
        assert results["infra.unreachable"].status == "unknown"


# --------------------------------------------------------------------------- #
# Gaps found by coverage measurement
# --------------------------------------------------------------------------- #
def test_crawl_delay_from_robots_is_obeyed():
    """`Crawl-delay: 1`: at least a second between two requests to the site."""
    import time

    moments: list[float] = []

    class Notebook(FakeSite):
        def route(self, path: str) -> Response:
            moments.append(time.monotonic())
            if path == "/robots.txt":
                return Response(b"User-agent: *\nCrawl-delay: 1\n", headers={"content-type": "text/plain"})
            return super().route(path)

    with Notebook() as site:
        scan(site, **{"http.max_requests_per_domain": 5})
    after_robots = moments[1:]
    gaps = [b - a for a, b in zip(after_robots, after_robots[1:], strict=False)]
    assert gaps and min(gaps) >= 0.9, f"gaps: {[round(r, 2) for r in gaps]}"


def test_broken_sitemap_in_index_falls_back_to_internal_links():
    with FakeSite(extra={"/sitemap-1.xml": Response(b"none", status=404)}) as site:
        snapshot = scan(site)
    assert snapshot.sitemap.status == 200, "the index exists"
    assert snapshot.sample_source == "links"
    assert any(p.url.endswith("/usluge") for p in snapshot.pages)


def test_exception_in_a_domain_gives_a_row_not_a_crash(monkeypatch):
    """U2: an exception while assembling a snapshot stays in that domain."""
    import sitetriage.fetch.http as http

    async def crashes(_fetcher, _target):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(http, "fetch_site", crashes)
    snapshots = asyncio.run(scan_domains([DomainInput(domain="puca.test")], load_config()))
    assert len(snapshots) == 1
    assert snapshots[0].errors and snapshots[0].errors[0].kind == "RuntimeError"


def test_client_without_certificate_verification_is_created_once():
    async def run():
        async with Fetcher(load_config()) as fetcher:
            first = fetcher._pick_client(verify=False)
            return first, fetcher._pick_client(verify=False), fetcher._pick_client(verify=True)

    first, second, verified = asyncio.run(run())
    assert first is second and first is not verified


@pytest.mark.parametrize(
    "exc, expected",
    [
        pytest.param(httpx.WriteTimeout("x", request=None), "timeout", id="ke-other-timeout"),
        pytest.param(httpx.PoolTimeout("x", request=None), "timeout", id="ke-pool-timeout"),
    ],
)
def test_classification_of_other_timeouts(exc, expected):
    assert _classify(exc)[0] == expected
