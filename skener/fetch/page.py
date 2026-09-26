"""Sirov odgovor → `PageSnapshot` (§3.2). Čisto: bez mreže, bez diska.

Odvojeno od `fetch.http` namerno: parsiranje je jedini deo dohvatanja koji ima
logiku, pa mora da se testira bez mreže — što je cela poenta §2.1.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from selectolax.lexbor import LexborHTMLParser

from skener.fetch.urls import collapse_ws, normalize, same_site
from skener.models import OpenGraph, PageSnapshot

RELEVANT_HEADERS = ("content-encoding", "content-type", "content-length", "cache-control", "vary")
TEXT_SAMPLE_CHARS = 4000
LINKS_KEPT = 200  # toliko internih veza ide u snapshot; za poređenje duplikata trebaju tri (Z-21)
OG_KEYS = {"og:title": "title", "og:description": "description", "og:image": "image", "og:url": "url"}

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
) -> PageSnapshot:
    """`keep_raw_html` je tačno za početnu stranu — inače snapshot naraste (§3.2)."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    page = PageSnapshot(
        url=url,
        final_url=final_url,
        status=status,
        redirect_hops=redirect_hops,
        elapsed_ms=elapsed_ms,
        headers={k: v for k, v in headers.items() if k in RELEVANT_HEADERS},
        html_bytes=len(body or b""),
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


def internal_links(html: str | None, base_url: str) -> list[str]:
    """Dopuna uzorka kad mapa sajta ne navodi dovoljno adresa (§4.4): interni `<a href>` sa početne."""
    if not html:
        return []
    return internal([anchor.attributes.get("href") for anchor in LexborHTMLParser(html).css("a")], base_url)


def internal(hrefs: list[str | None], base_url: str) -> list[str]:
    """Interne adrese, normalizovane, bez ponavljanja, redom prvog pojavljivanja."""
    targets = (normalize(href, base_url) for href in hrefs)
    return list(dict.fromkeys(t for t in targets if t and same_site(t, base_url)))


def _decode(body: bytes, content_type: str) -> str:
    """Zaglavlje, pa `<meta charset>`, pa utf-8.

    Stari srpski sajtovi ume da serviraju windows-1250 bez zaglavlja; pogrešno
    dekodiranje pokvari brojanje dijakritika, a od njega zavisi §5.1.
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
        # `property` je standard za OG, ali dosta sajtova koristi `name`.
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
