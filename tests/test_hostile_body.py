"""A response body from someone else's server has a hard limit, also after decompression.

A run scans hundreds of sites we do not control. One of them may send 65 kB of gzip that
decompresses to 64 MB, a body that never ends or a body that trickles in byte by byte, but it must
not use up the machine's memory or stop the run. A body over the limit is cut, and a check that
reads the whole HTML then says `unknown` with a reason; it claims nothing about what was not read.
"""

from __future__ import annotations

import asyncio
import time
import tracemalloc

import pytest
from factories import run_level
from localserver import FakeSite, Response, bomb, endless, html
from test_fetch_http import scan

from sitetriage.config import get, load_config
from sitetriage.fetch.http import DomainBudget, Fetcher, fetch_site
from sitetriage.messages import reason, render
from sitetriage.models import DomainInput

KB = 1024
HTML_PREFIX = b"<!doctype html><html lang='sr'><head><title>Bomba</title></head><body><h1>Bomba</h1>"


def default_limit() -> int:
    return get(load_config(), "http.max_body_kb") * KB


# --------------------------------------------------------------------------- #
# The default limits do not change the result on an ordinary site
# --------------------------------------------------------------------------- #
def test_default_limits_are_above_every_html_threshold():
    """The limit is for a hostile site, not a threshold: ordinary HTML stays whole.

    The `perf.html.size` threshold is 500 kB.
    """
    cfg = load_config()
    limit = get(cfg, "http.max_body_kb") * KB
    assert limit >= 10 * get(cfg, "thresholds.perf.html_size_kb") * KB
    assert limit >= 10 * get(cfg, "escalation.raw_html_bytes")
    # The same limit as before (10 MB), only now it also applies to a decompressed `.xml.gz`.
    assert get(cfg, "sitemap.max_kb") * KB == 10 * 1024 * 1024


# --------------------------------------------------------------------------- #
# A decompression bomb in HTML
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_pg_html_bomb_is_cut_at_the_limit(encoding):
    """65 kB on the wire, 64 MB decompressed: the home page is read up to `http.max_body_kb`, truncated."""
    body = bomb(64 * 1024 * KB, encoding=encoding, prefix=HTML_PREFIX)
    assert len(body) < 200 * KB
    home_page = Response(body, headers={"content-encoding": encoding}, encoded=True)
    with FakeSite(extra={"/": home_page}) as site:
        snapshot = scan(site)

    home = snapshot.home
    assert snapshot.entry.status == 200 and home.status == 200
    assert home.truncated is True
    assert home.html_bytes == default_limit()
    assert home.title == "Bomba", "what arrived before the limit is still read"


def test_pg_html_bomb_does_not_take_memory_beyond_the_limit():
    """Peak memory follows the limit, not the decompressed size: a 1 MB limit, a 64 MB bomb."""
    body = bomb(64 * 1024 * KB, prefix=HTML_PREFIX)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["http"]["max_body_kb"] = 1024

    async def one_request(url: str):
        async with Fetcher(cfg) as fetcher:
            return await fetcher.request(url, DomainBudget(5, 30), retries=0)

    with FakeSite(extra={"/": Response(body, headers={"content-encoding": "gzip"}, encoded=True)}) as site:
        tracemalloc.start()
        try:
            outcome = asyncio.run(one_request(f"{site.base_url}/"))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert outcome.ok and outcome.truncated
    assert len(outcome.body) == 1024 * KB
    assert peak < 16 * 1024 * KB, f"memory peak {peak} B for a 1 MB limit"


def test_pg_bomb_in_a_redirect_is_not_decompressed():
    """The body of a redirecting response is not read: httpx would otherwise decompress all of it first."""
    redirect = Response(
        bomb(64 * 1024 * KB),
        status=302,
        headers={"content-encoding": "gzip", "location": "/pocetna"},
        encoded=True,
    )
    with FakeSite(extra={"/": redirect, "/pocetna": Response(html("Prava početna"))}) as site:
        tracemalloc.start()
        try:
            snapshot = scan(site, **{"http.max_body_kb": 1024})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert snapshot.home.title == "Prava početna"
    assert snapshot.entry.redirect_chain == [f"{site.base_url}/", f"{site.base_url}/pocetna"]
    assert peak < 16 * 1024 * KB, f"memory peak {peak} B for a 1 MB limit"


# --------------------------------------------------------------------------- #
# A body that never ends
# --------------------------------------------------------------------------- #
def test_pg_endless_body_is_cut_and_the_run_goes_on():
    """The server sends without end or Content-Length: read up to the limit, then the rest is scanned."""
    with FakeSite(extra={"/": Response(chunks=endless(HTML_PREFIX + b" " * 65536))}) as site:
        started = time.monotonic()
        snapshot = scan(site, **{"http.max_body_kb": 256})
        duration = time.monotonic() - started

    assert snapshot.home.truncated and snapshot.home.html_bytes == 256 * KB
    assert snapshot.robots.status == 200, "scanning goes on after a truncated home page"
    assert len(snapshot.pages) > 1
    assert duration < 15


def test_pg_trickling_body_has_a_total_deadline():
    """A byte every 0.2 s never trips the read timeout (10 s), so `http.timeout_total_s` applies."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["http"]["timeout_total_s"] = 1

    async def run(site: FakeSite):
        async with Fetcher(cfg) as fetcher:
            return await asyncio.wait_for(fetch_site(fetcher, DomainInput(domain=site.base_url)), 15)

    drip = Response(chunks=endless(b"x", pause=0.2))
    with FakeSite(extra={"/": drip}) as site:
        started = time.monotonic()
        snapshot = asyncio.run(run(site))
        duration = time.monotonic() - started

    assert snapshot.entry.error_kind == "timeout"
    assert "http.timeout_total_s" in snapshot.entry.error_detail
    assert duration < 10, "it is retried once, so that is two 1 s deadlines and a delay"


# --------------------------------------------------------------------------- #
# Boundary values: exactly the limit passes, the limit + 1 is cut
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("encoding", [None, "gzip"], ids=["no-compression", "gzip"])
@pytest.mark.parametrize(
    "excess, truncated",
    [
        pytest.param(-1, False, id="gv-limit-minus-1"),
        pytest.param(0, False, id="gv-exactly-limit"),
        pytest.param(1, True, id="gv-limit-plus-1"),
    ],
)
def test_gv_body_limit(encoding, excess, truncated):
    limit = 64 * KB
    body = HTML_PREFIX + b" " * (limit + excess - len(HTML_PREFIX))
    headers = {"content-encoding": encoding} if encoding else {}
    with FakeSite(extra={"/": Response(body, headers=headers)}) as site:
        snapshot = scan(site, **{"http.max_body_kb": 64})

    assert snapshot.home.truncated is truncated
    assert snapshot.home.html_bytes == min(len(body), limit)


# --------------------------------------------------------------------------- #
# Checks on a truncated home page claim nothing about what was not read
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def truncated_home():
    """A home page cut at 64 kB: the title, description and canonical could be after the limit."""
    body = b"<!doctype html><html><body>" + b"<p>tekst</p>" * 20_000
    with FakeSite(extra={"/": Response(body)}) as site:
        return scan(site, **{"http.max_body_kb": 64})


@pytest.mark.parametrize(
    "check_id",
    [
        "seo.title.missing",
        "seo.description.missing",
        "seo.canonical.missing",
        "seo.title.duplicate",
        "social.og.title.missing",
        "i18n.lang.missing",
        "i18n.lang.mismatch",
    ],
)
def test_content_check_on_truncated_home_is_unknown(truncated_home, check_id):
    result = run_level(1, truncated_home)[check_id]
    assert result.status == "unknown"
    assert result.reason.code == "requires.home_complete"
    assert reason(result.reason, "sr") and reason(result.reason, "en")


def test_size_of_truncated_home_is_a_finding_of_at_least_that_size(truncated_home):
    """Cut at 64 kB means "more than 64 kB": that is still true, just without the exact number."""
    results = run_level(1, truncated_home)
    finding = results["perf.compression.missing"].findings[0]
    assert finding.variant == "truncated"
    assert "više od 64 kB" in render(finding, "sr").client
    assert "more than 64 kB" in render(finding, "en").client
    # The 500 kB threshold is above what was read, so whether the HTML is too large is unknown.
    size = results["perf.html.size"]
    assert size.status == "unknown" and size.reason.code == "body_truncated"
    assert "64 kB" in reason(size.reason, "sr")


def test_size_of_truncated_home_above_the_threshold_is_a_finding():
    body = b"<!doctype html><html><body>" + b"<p>tekst</p>" * 60_000
    with FakeSite(extra={"/": Response(body)}) as site:
        snapshot = scan(site, **{"http.max_body_kb": 600})
    finding = run_level(1, snapshot)["perf.html.size"].findings[0]
    assert finding.variant == "truncated"
    assert "više od 600 kB" in render(finding, "sr").client
    assert "more than 600 kB" in render(finding, "en").client


# --------------------------------------------------------------------------- #
# An .xml.gz sitemap that decompresses beyond the limit
# --------------------------------------------------------------------------- #
def test_pg_sitemap_gz_bomb_is_not_a_missing_sitemap_finding():
    """The sitemap exists, it is just too large: `infra.sitemap.missing` is `unknown`, not a finding."""
    robots = b"User-agent: *\nSitemap: {base}/sitemap.xml.gz\n"
    xml = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    gz = {"content-type": "application/gzip"}
    sitemap = Response(bomb(64 * 1024 * KB, prefix=xml), headers=gz, encoded=True)
    with FakeSite(extra={"/sitemap.xml.gz": sitemap}) as site:
        site.extra["/robots.txt"] = Response(robots.replace(b"{base}", site.base_url.encode()))
        snapshot = scan(site)

    assert snapshot.sitemap.status == 200
    assert snapshot.sitemap.urls == [] and snapshot.sitemap.truncated
    result = run_level(1, snapshot)["infra.sitemap.missing"]
    assert result.status == "unknown" and result.reason.code == "sitemap_too_large"
    assert snapshot.sample_source == "links", "the sample is topped up with links from the home page"


# --------------------------------------------------------------------------- #
# Decompression chunk by chunk: the same as httpx, but without a chunk larger than the step limit
# --------------------------------------------------------------------------- #
def _decompress(encodings: list[str], data: bytes) -> bytes:
    from sitetriage.fetch.http import _Decoder

    r = _Decoder(encodings)
    return b"".join([*r.decode(data[:7]), *r.decode(data[7:]), *r.flush()])


CONTENT = HTML_PREFIX * 50


@pytest.mark.parametrize(
    "encodings, compress",
    [
        pytest.param(["gzip"], lambda d: zlib_compress(d, 31), id="gzip"),
        pytest.param(["deflate"], lambda d: zlib_compress(d, 15), id="deflate-zlib"),
        pytest.param(["deflate"], lambda d: zlib_compress(d, -15), id="deflate-raw"),
        pytest.param(["identity"], lambda d: d, id="identity"),
        pytest.param(["br"], lambda d: d, id="unknown-stays-as-it-arrived"),
        pytest.param(
            ["gzip", " Deflate"], lambda d: zlib_compress(zlib_compress(d, 31), 15), id="two-encodings"
        ),
    ],
)
def test_decompression_like_httpx(encodings, compress):
    assert _decompress(encodings, compress(CONTENT)) == CONTENT


def zlib_compress(data: bytes, wbits: int) -> bytes:
    import zlib

    compressor = zlib.compressobj(9, zlib.DEFLATED, wbits)
    return compressor.compress(data) + compressor.flush()


def test_decompression_returns_no_chunk_larger_than_the_step():
    from sitetriage.fetch.http import DECOMPRESSED_PER_STEP, _Decoder

    chunks = list(_Decoder(["gzip"]).decode(bomb(8 * 1024 * KB)))
    assert sum(map(len, chunks)) == 8 * 1024 * KB
    assert max(map(len, chunks)) <= DECOMPRESSED_PER_STEP


def test_pg_broken_gzip_is_a_connection_error_as_before():
    """httpx raised `DecodingError` for broken gzip, and that is the `connection` kind."""
    body = Response(b"not gzip at all", headers={"content-encoding": "gzip"}, encoded=True)
    with FakeSite(extra={"/": body}) as site:
        snapshot = scan(site)
    assert snapshot.entry.error_kind == "connection"
    assert "DecodingError" in snapshot.entry.error_detail


def test_pg_endless_redirect_loop_is_still_too_many_redirects():
    """Redirects are now followed by hand; the httpx limit (20 hops) must stay the same."""
    loop = Response(status=302, headers={"location": "/"})
    with FakeSite(extra={"/": loop}) as site:
        snapshot = scan(site)
    assert snapshot.entry.error_kind == "too_many_redirects"
    assert site.paths().count("/") == 21, "the first request and 20 hops, without a retry, as before"
