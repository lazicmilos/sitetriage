"""Parsing robots.txt, sitemaps and HTML. Pure functions, no network."""

from __future__ import annotations

import gzip
import tracemalloc

import pytest

from sitetriage.config import get, load_config
from sitetriage.fetch import robots, sitemap
from sitetriage.fetch.page import STUB_MAX_TEXT, build, internal_links, redirect_stub

# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #
ROBOTS = """
# comment
User-agent: AhrefsBot
Disallow: /

User-agent: *
Crawl-delay: 2
Disallow: /admin
Disallow: /*.pdf$
Allow: /admin/javno
Disallow:

Sitemap: https://d.rs/sitemap_index.xml
"""


def test_reads_only_the_star_group_and_global_sitemaps():
    rules = robots.parse(ROBOTS)
    assert rules.disallow == ("/admin", "/*.pdf$")
    assert rules.allow == ("/admin/javno",)
    assert rules.crawl_delay == 2.0
    assert rules.sitemaps == ("https://d.rs/sitemap_index.xml",)


@pytest.mark.parametrize(
    "path, allowed",
    [
        ("/", True),
        ("/o-nama", True),
        ("/admin", False),
        ("/admin/tajno", False),
        ("/admin/javno", True),  # Allow with the longer match wins
        ("/admin/javno/x", True),
        ("/uputstvo.pdf", False),  # $ anchor
        ("/uputstvo.pdf?v=2", True),  # does not end in .pdf
        ("https://d.rs/admin/tajno", False),  # a full URL, not just a path
    ],
)
def test_prefix_matching_with_star_and_dollar(path, allowed):
    assert robots.allows(robots.parse(ROBOTS), path) is allowed


def test_empty_robots_allows_everything():
    assert robots.allows(robots.parse(None), "/bilo/sta") is True
    assert robots.parse("").disallow == ()


def test_disallow_without_value_blocks_nothing():
    rules = robots.parse("User-agent: *\nDisallow:\n")
    assert rules.disallow == ()
    assert robots.allows(rules, "/bilo/sta") is True


def test_rules_for_another_bot_do_not_apply_to_us():
    rules = robots.parse("User-agent: Googlebot\nDisallow: /tajno\n")
    assert robots.allows(rules, "/tajno") is True


def test_shared_group_for_several_agents():
    rules = robots.parse("User-agent: Googlebot\nUser-agent: *\nDisallow: /tajno\n")
    assert robots.allows(rules, "/tajno") is False


# --------------------------------------------------------------------------- #
# sitemap
# --------------------------------------------------------------------------- #
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
INDEX = f'<sitemapindex {NS}><sitemap><loc>https://d.rs/s1.xml</loc></sitemap></sitemapindex>'.encode()
URLSET = f'<urlset {NS}><url><loc>https://d.rs/a</loc></url><url><loc>https://d.rs/b</loc></url></urlset>'.encode()


# The limit comes from sitetriage.toml (`sitemap.max_kb`), not from code.
MAX = get(load_config(), "sitemap.max_kb") * 1024


def parse(data: bytes | None, max_bytes: int = MAX):
    return sitemap.parse(data, max_bytes=max_bytes)


def test_recognizes_index_and_urlset():
    assert parse(INDEX) == ("index", ["https://d.rs/s1.xml"])
    assert parse(URLSET) == ("urlset", ["https://d.rs/a", "https://d.rs/b"])


def test_supports_gzip():
    assert parse(gzip.compress(URLSET))[1] == ["https://d.rs/a", "https://d.rs/b"]


def test_blank_line_before_xml_declaration_is_tolerated():
    """A WordPress plugin that prints a blank line before `<?xml` does not erase the sitemap (BUG-028)."""
    assert parse(b'\n<?xml version="1.0" encoding="UTF-8"?>' + INDEX)[0] == "index"


@pytest.mark.parametrize("data", [None, b"", b"<html>404</html>", b"{ not xml }", b"\x1f\x8b broken gzip"])
def test_garbage_does_not_crash_the_parser(data):
    kind, urls = parse(data)
    assert kind == "unknown" and urls == []


def test_oversized_sitemap_is_refused():
    """Trust boundary: the content is from someone else's server. A too large sitemap is not "no sitemap"."""
    huge = b"<urlset>" + b"<url><loc>https://d.rs/a</loc></url>" * 400_000 + b"</urlset>"
    assert len(huge) > MAX
    assert parse(huge) == ("too_large", [])


def _urlset_exactly(size: int) -> bytes:
    """A valid urlset of exactly `size` bytes: spaces before the closing tag."""
    start, end = URLSET[: -len(b"</urlset>")], b"</urlset>"
    return start + b" " * (size - len(start) - len(end)) + end


@pytest.mark.parametrize("compressed", [False, True], ids=["xml", "xml.gz"])
@pytest.mark.parametrize(
    "excess, kind",
    [
        pytest.param(0, "urlset", id="gv-exactly-limit"),
        pytest.param(1, "too_large", id="gv-limit-plus-1"),
    ],
)
def test_gv_sitemap_limit_also_applies_after_decompression(compressed, excess, kind):
    limit = 4096
    data = _urlset_exactly(limit + excess)
    assert len(data) == limit + excess
    assert parse(gzip.compress(data) if compressed else data, max_bytes=limit)[0] == kind


def test_pg_gzip_bomb_in_sitemap_is_not_decompressed_in_full():
    """A ~50 kB `.xml.gz` that decompresses to 50 MB: memory follows the limit, not the decompressed size."""
    bomb = gzip.compress(b"<urlset>" + b" " * 50 * 1024 * 1024, compresslevel=9)
    assert len(bomb) < 100 * 1024
    limit = 1024 * 1024
    tracemalloc.start()
    try:
        result = parse(bomb, max_bytes=limit)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result == ("too_large", [])
    assert peak < 4 * limit, f"memory peak {peak} B for a limit of {limit} B"


def test_multi_member_gzip_is_read_in_full():
    """`cat a.gz b.gz` is valid gzip; `gzip.decompress` read all of it, so it still must be."""
    half = len(URLSET) // 2
    data = gzip.compress(URLSET[:half]) + gzip.compress(URLSET[half:])
    assert parse(data)[1] == ["https://d.rs/a", "https://d.rs/b"]


def test_truncated_sitemap_gzip_is_not_a_sitemap():
    """Gzip cut in half (the server closed the connection) gives what was decompressed, which is not XML."""
    assert parse(gzip.compress(URLSET * 50)[:40]) == ("unknown", [])


def test_sampling_is_deterministic_and_grouped():
    """Round robin over path groups, so you do not get eight blog posts."""
    urls = [
        *[f"https://d.rs/blog/{i}" for i in range(20)],
        "https://d.rs/usluge/a",
        "https://d.rs/usluge/b",
        "https://d.rs/o-nama",
    ]
    picked = sitemap.sample("https://d.rs/", urls, 4)
    assert picked == ["https://d.rs/", "https://d.rs/blog/0", "https://d.rs/usluge/a", "https://d.rs/o-nama"]
    # The same input in another order gives the same sample; otherwise no test means anything.
    assert sitemap.sample("https://d.rs/", list(reversed(urls)), 4) == picked


def test_sampling_does_not_duplicate_the_home_page():
    picked = sitemap.sample("https://d.rs/", ["https://d.rs/", "https://d.rs/a"], 8)
    assert picked == ["https://d.rs/", "https://d.rs/a"]


def test_sampling_skips_foreign_domains():
    """A sitemap is someone else's content: a foreign host in it must not spend this domain's budget."""
    urls = ["https://drugi.rs/a", "https://www.d.rs/usluge", "https://d.rs/o-nama"]
    picked = sitemap.sample("https://d.rs/", urls, 8)
    assert picked == ["https://d.rs/", "https://d.rs/o-nama", "https://www.d.rs/usluge"]


def test_sampling_respects_the_size():
    urls = [f"https://d.rs/g{i}/x" for i in range(50)]
    assert len(sitemap.sample("https://d.rs/", urls, 8)) == 8


# --------------------------------------------------------------------------- #
# HTML → PageSnapshot
# --------------------------------------------------------------------------- #
HTML = """<!doctype html><html lang="sr-Latn-RS">
<head><title>  Naslov   sajta </title>
<meta name="Description" content="Opis  sajta">
<meta property="og:title" content="OG naslov">
<meta name="og:image" content="https://d.rs/s.jpg">
<link rel="canonical" href="/usluge/?utm_source=fb">
<link rel="alternate" hreflang="en" href="/en/">
</head><body><h1>A</h1><h1>B</h1>
<script>var x = "nevidljivo";</script><style>.a{color:red}</style>
<p>Vidljiv tekst sa čćšžđ.</p>
<a href="/o-nama">o nama</a><a href="https://drugi.rs/x">van</a><a href="#vrh">vrh</a>
</body></html>"""


def test_builds_snapshot_from_html():
    page = build(
        "https://d.rs/",
        final_url="https://d.rs/",
        status=200,
        headers={"Content-Encoding": "gzip", "X-Irrelevant": "1"},
        body=HTML.encode(),
        keep_raw_html=True,
    )
    assert page.title == "Naslov sajta"
    assert page.meta_description == "Opis sajta"
    assert page.og.title == "OG naslov"
    assert page.og.image == "https://d.rs/s.jpg"  # `name=` instead of `property=` is still read
    assert page.canonical == "/usluge/?utm_source=fb"
    assert page.canonical_normalized == "https://d.rs/usluge"  # normalized before comparison
    assert page.lang == "sr-Latn-RS"
    assert page.hreflang == ["en"]
    assert page.h1_count_raw == 2
    assert page.headers == {"content-encoding": "gzip"}  # only the relevant headers


def test_text_leaves_out_script_and_style():
    page = build("https://d.rs/", final_url=None, status=200, body=HTML.encode())
    assert "nevidljivo" not in page.text_sample
    assert "color:red" not in page.text_sample
    assert "Vidljiv tekst sa čćšžđ." in page.text_sample


def test_raw_html_is_kept_only_when_asked():
    body = HTML.encode()
    assert build("https://d.rs/", final_url=None, status=200, body=body).raw_html is None
    assert build("https://d.rs/", final_url=None, status=200, body=body, keep_raw_html=True).raw_html


def test_empty_body_does_not_crash_the_parser():
    page = build("https://d.rs/", final_url=None, status=500, body=None)
    assert page.status == 500 and page.html_bytes == 0 and page.title is None


def test_decodes_windows_1250_from_meta_tag():
    """Wrong decoding breaks the diacritics count that the language heuristic depends on."""
    body = '<html><head><meta charset="windows-1250"></head><body>čćšžđ</body></html>'.encode("windows-1250")
    assert "čćšžđ" in build("https://d.rs/", final_url=None, status=200, body=body).text_sample


def test_internal_links_without_fragments_or_foreign_hosts():
    assert internal_links(HTML, "https://d.rs/") == ["https://d.rs/o-nama"]


# --------------------------------------------------------------------------- #
# BUG-022: a page without text that only redirects is a hop, like an HTTP redirect
# --------------------------------------------------------------------------- #
def _stub(head: str, text: str = "") -> object:
    html = f"<html><head>{head}</head><body>{text}</body></html>"
    body = html.encode()
    return build("https://d.rs/", final_url="https://d.rs/", status=200, body=body, keep_raw_html=True)


@pytest.mark.parametrize(
    "head, expected",
    [
        pytest.param(
            "<script>location.replace('/uskoro/')</script>", "https://d.rs/uskoro/", id="tab-js-replace"
        ),
        pytest.param('<script>window.location.href = "https://www.d.rs/novo"</script>', "https://www.d.rs/novo",
                     id="tab-js-href-www"),
        pytest.param(
            """<meta http-equiv="Refresh" content="0; URL='/sr/'">""",
            "https://d.rs/sr/",
            id="tab-meta-refresh",
        ),
        pytest.param("<script>location.href = 'https://drugi.rs/'</script>", None, id="tab-foreign-site"),
        pytest.param('<meta http-equiv="refresh" content="30">', None, id="tab-refresh-without-url"),
        pytest.param("<script>location.href = '/'</script>", None, id="tab-same-page"),
        pytest.param("<script>if (location.href == '/x') go()</script>", None, id="tab-comparison-not-a-hop"),
        pytest.param("<script>location.assign(target)</script>", None, id="tab-variable"),
    ],
)
def test_page_that_only_redirects(head, expected):
    assert redirect_stub(_stub(head)) == expected


@pytest.mark.parametrize(
    "chars, expected",
    [
        pytest.param(STUB_MAX_TEXT, "https://d.rs/uskoro/", id="gv-text-at-limit"),
        pytest.param(STUB_MAX_TEXT + 1, None, id="gv-text-over-limit"),
    ],
)
def test_page_with_text_is_not_a_stub(chars, expected):
    """The same statement on a real page is conditional or runs on a click."""
    page = _stub("<script>location.replace('/uskoro/')</script>", "x" * chars)
    assert page.text_length == chars
    assert redirect_stub(page) == expected
