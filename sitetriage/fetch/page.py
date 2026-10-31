"""Raw response → `PageSnapshot`. Pure: no network, no disk.

Kept apart from `fetch.http` on purpose: parsing is the only part of fetching that has
logic, so it must be testable without a network. That is the whole point of keeping the
network layer apart from the checks.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from sitetriage.fetch.urls import collapse_ws, normalize, same_site
from sitetriage.models import OpenGraph, PageSnapshot

RELEVANT_HEADERS = ("content-encoding", "content-type", "content-length", "cache-control", "vary")
TEXT_SAMPLE_CHARS = 4000
LINKS_KEPT = 200  # this many internal links go into the snapshot; duplicate checks need three (ADR-015)
OG_KEYS = {"og:title": "title", "og:description": "description", "og:image": "image", "og:url": "url"}

# A page with this much visible text or less that only redirects is a "stub" (BUG-022).
STUB_MAX_TEXT = 100
_REFRESH = re.compile(r"""^\s*[\d.]*\s*[;,]\s*(?:url\s*=\s*)?['"]?([^'"\s]+)""", re.I)
_JS_LOCATION = re.compile(
    r"""\blocation(?:\.href)?\s*=\s*['"]([^'"]+)['"]|\blocation\.(?:replace|assign)\(\s*['"]([^'"]+)['"]"""
)

_CHARSET_HEADER = re.compile(r"charset=([\w-]+)", re.I)
_CHARSET_META = re.compile(rb"""charset=["']?([\w-]+)""", re.I)


def build(
    url: str,
    *,
    final_url: str | None,
    status: int | None,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    elapsed_ms: int | None = None,
    redirect_hops: int = 0,
    keep_raw_html: bool = False,
    truncated: bool = False,
) -> PageSnapshot:
    """`keep_raw_html` is true for the home page only; otherwise snapshots grow.

    `truncated`: the body was cut at `http.max_body_kb`, so `html_bytes` is a lower bound of the size.
    """
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    page = PageSnapshot(
        url=url,
        final_url=final_url,
        status=status,
        redirect_hops=redirect_hops,
        elapsed_ms=elapsed_ms,
        headers={k: v for k, v in headers.items() if k in RELEVANT_HEADERS},
        html_bytes=len(body or b""),
        truncated=truncated,
    )
    if not body:
        return page

    html = _decode(body, headers.get("content-type", ""))
    if keep_raw_html:
        page.raw_html = html

    tree = LexborHTMLParser(html)
    base = final_url or url
    page.title = collapse_ws(tree.css_first("title").text()) if tree.css_first("title") else None
    page.h1_count_raw = len(tree.css("h1"))
    page.meta_description, og_values = _read_meta(tree)
    page.og = OpenGraph(**og_values)
    page.canonical, page.hreflang = _read_links(tree)
    page.canonical_normalized = normalize(page.canonical, base)

    html_tag = tree.css_first("html")
    page.lang = html_tag.attributes.get("lang") if html_tag else None

    text = _visible_text(tree)
    page.text_sample = text[:TEXT_SAMPLE_CHARS]
    page.text_length = len(text)
    return page


def redirect_stub(page: PageSnapshot) -> str | None:
    """The same-site URL that a page without text redirects to with meta refresh or JavaScript.

    A browser and Google skip that page like an HTTP redirect; level 1 used to score it (BUG-022).
    Only a page without text: the same statement on a real page is conditional or runs on a click.
    """
    if not page.raw_html or (page.text_length or 0) > STUB_MAX_TEXT:
        return None
    tree = LexborHTMLParser(page.raw_html)
    targets = [
        m.group(1)
        for meta in tree.css("meta[http-equiv]")
        if (meta.attributes.get("http-equiv") or "").lower() == "refresh"
        and (m := _REFRESH.match(meta.attributes.get("content") or ""))
    ]
    for script in tree.css("script"):
        targets += [a or b for a, b in _JS_LOCATION.findall(script.text() or "")]
    base = page.final_url or page.url
    for target in targets:
        url = urljoin(base, target.strip())
        if normalize(url) and same_site(url, base) and normalize(url) != normalize(base):
            return url
    return None


def internal_links(html: str | None, base_url: str) -> list[str]:
    """Top-up of the sample when the sitemap lists too few URLs: internal `<a href>` from the home page."""
    if not html:
        return []
    return internal([anchor.attributes.get("href") for anchor in LexborHTMLParser(html).css("a")], base_url)


def internal(hrefs: list[str | None], base_url: str) -> list[str]:
    """Internal URLs, normalized, without repeats, in order of first appearance."""
    targets = (normalize(href, base_url) for href in hrefs)
    return list(dict.fromkeys(t for t in targets if t and same_site(t, base_url)))


def _decode(body: bytes, content_type: str) -> str:
    """The header, then `<meta charset>`, then utf-8.

    Old Serbian sites sometimes serve windows-1250 without a header; decoding it wrongly
    breaks the diacritics count that the language heuristic depends on.
    """
    header_match = _CHARSET_HEADER.search(content_type)
    meta_match = _CHARSET_META.search(body[:2048])
    for candidate in (header_match, meta_match):
        if candidate:
            encoding = candidate.group(1)
            encoding = encoding.decode() if isinstance(encoding, bytes) else encoding
            try:
                return body.decode(encoding, errors="replace")
            except LookupError:
                continue
    return body.decode("utf-8", errors="replace")


def _read_meta(tree: LexborHTMLParser) -> tuple[str | None, dict[str, str | None]]:
    description: str | None = None
    og: dict[str, str | None] = {"title": None, "description": None, "image": None, "url": None}
    for meta in tree.css("meta"):
        attrs = meta.attributes
        content = collapse_ws(attrs.get("content"))
        if not content:
            continue
        # `property` is the standard for OG, but many sites use `name`.
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        if key == "description" and description is None:
            description = content
        elif key in OG_KEYS and og[OG_KEYS[key]] is None:
            og[OG_KEYS[key]] = content
    return description, og


def _read_links(tree: LexborHTMLParser) -> tuple[str | None, list[str]]:
    canonical: str | None = None
    hreflang: list[str] = []
    for link in tree.css("link"):
        attrs = link.attributes
        rel = (attrs.get("rel") or "").lower().split()
        if "canonical" in rel and canonical is None:
            canonical = (attrs.get("href") or "").strip() or None
        if "alternate" in rel and attrs.get("hreflang"):
            hreflang.append(attrs["hreflang"].strip())
    return canonical, hreflang


def _visible_text(tree: LexborHTMLParser) -> str:
    for node in tree.css("script, style, noscript, template"):
        node.decompose()
    root = tree.body or tree.root
    return collapse_ws(root.text(separator=" ")) or "" if root else ""
