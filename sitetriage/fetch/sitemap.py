"""Sitemap: parsing, recursion and deterministic sampling.

Parsing and sampling are pure functions; `fetch.http` does the recursive fetching by calling
`parse` in a loop, with the limits from the configuration.
"""

from __future__ import annotations

import zlib
from collections import defaultdict
from collections.abc import Iterable
from typing import Literal
from xml.etree import ElementTree

from sitetriage.fetch.urls import normalize, path_group, same_site

# `too_large`: the sitemap exists but is larger than the limit, so what it lists is not known.
SitemapKind = Literal["index", "urlset", "unknown", "too_large"]

GZIP_MAGIC = b"\x1f\x8b"


def parse(data: bytes | None, *, max_bytes: int) -> tuple[SitemapKind, list[str]]:
    """Returns (kind, locations). Supports `.xml.gz`, of which there are plenty.

    ponytail: a hard limit on the input instead of a defusedxml dependency. A sitemap is content
    from someone else's server, so `max_bytes` (`sitemap.max_kb`) is the trust boundary, and it
    applies to the decompressed size: 50 kB of gzip can be 50 MB. If a full shield against XML
    bombs is ever needed, `defusedxml.ElementTree` is a one-line replacement.
    """
    if not data:
        return "unknown", []
    if data[:2] == GZIP_MAGIC:
        try:
            data = _gunzip(data, max_bytes + 1)
        except zlib.error:
            return "unknown", []
    if len(data) > max_bytes:
        return "too_large", []
    # A blank line before `<?xml` (common on WordPress) is an XML error, yet the sitemap exists (BUG-028).
    data = data.lstrip()

    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return "unknown", []

    kind: SitemapKind = {"sitemapindex": "index", "urlset": "urlset"}.get(
        _tag(root), "unknown"
    )
    if kind == "unknown":
        return kind, []

    wanted = "sitemap" if kind == "index" else "url"
    locations = [
        loc.text.strip()
        for entry in root
        if _tag(entry) == wanted
        for loc in entry
        if _tag(loc) == "loc" and loc.text and loc.text.strip()
    ]
    return kind, locations


def _gunzip(data: bytes, limit: int) -> bytes:
    """At most `limit` bytes of decompressed gzip, chunk by chunk, also for several members (`cat a.gz b.gz`).

    A truncated gzip gives what was decompressed up to the cut, where `gzip.decompress` would fail.
    """
    out = bytearray()
    while len(out) < limit:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out += decompressor.decompress(data, limit - len(out))
        data = decompressor.unused_data
        if not decompressor.eof or data[:2] != GZIP_MAGIC:
            break
    return bytes(out)


def _tag(element: ElementTree.Element) -> str:
    """Strips the XML namespace: `{http://…}urlset` → `urlset`."""
    return element.tag.rpartition("}")[2].lower()


def sample(home_url: str, urls: Iterable[str], sample_size: int) -> list[str]:
    """Deterministic sampling: the home page, then round robin over path groups.

    Grouping by the first path segment matters: the lexicographically first 8 URLs give
    eight blog posts and miss that the service pages are all the same.

    Without a fixed order the same site gives different findings in two runs and no test
    means anything, which is why there is no `random` anywhere.
    """
    home = normalize(home_url)
    picked = [home] if home else []
    remaining = max(sample_size - len(picked), 0)
    if remaining == 0:
        return picked

    groups: dict[str, set[str]] = defaultdict(set)
    for url in urls:
        canonical = normalize(url)
        # A sitemap is someone else's content: a foreign host in it does not spend this domain's budget.
        if canonical and canonical != home and same_site(canonical, home_url):
            groups[path_group(canonical)].add(canonical)

    # Groups: by size descending, then by name, so that a tie does not depend on
    # insertion order. URLs inside a group: lexicographically.
    ordered = [
        sorted(members)
        for _, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]

    for round_index in range(max((len(g) for g in ordered), default=0)):
        for group in ordered:
            if len(picked) >= sample_size:
                return picked
            if round_index < len(group):
                picked.append(group[round_index])
    return picked
