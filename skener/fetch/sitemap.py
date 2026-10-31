"""Sitemap: parsiranje, rekurzija i determinističko uzorkovanje (§4.4).

Parsiranje i uzorkovanje su čiste funkcije; rekurzivno dohvatanje radi
`fetch.http` pozivajući `parse` u petlji sa ograničenjima iz konfiguracije.
"""

from __future__ import annotations

import zlib
from collections import defaultdict
from collections.abc import Iterable
from typing import Literal
from xml.etree import ElementTree

from skener.fetch.urls import normalize, path_group, same_site

# `too_large`: mapa postoji, ali je veća od granice, pa se ne zna šta navodi.
SitemapKind = Literal["index", "urlset", "unknown", "too_large"]

GZIP_MAGIC = b"\x1f\x8b"


def parse(data: bytes | None, *, max_bytes: int) -> tuple[SitemapKind, list[str]]:
    """Vraća (vrsta, lokacije). Podržava `.xml.gz` — ima ih dosta (§4.4).

    ponytail: tvrd limit na ulaz umesto defusedxml zavisnosti. Sitemap je sadržaj sa tuđeg
    servera, pa je `max_bytes` (`sitemap.max_kb`) granica poverenja, i to za raspakovanu
    veličinu: gzip od 50 kB je i 50 MB. Ako ikad zatreba pun štit od XML bombi,
    `defusedxml.ElementTree` je zamena u jednom redu.
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
    # Prazan red pre `<?xml` (čest WordPress kvar) je za XML greška, ali mapa sajta postoji (BUG-028).
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
    """Najviše `limit` bajtova raspakovanog gzip-a, deo po deo, i kad ima više delova (`cat a.gz b.gz`).

    Prekinut gzip daje ono što je raspakovano do prekida, a `gzip.decompress` bi tu pukao.
    """
    out = bytearray()
    while len(out) < limit:
        raspakivac = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out += raspakivac.decompress(data, limit - len(out))
        data = raspakivac.unused_data
        if not raspakivac.eof or data[:2] != GZIP_MAGIC:
            break
    return bytes(out)


def _tag(element: ElementTree.Element) -> str:
    """Skida XML namespace: `{http://…}urlset` → `urlset`."""
    return element.tag.rpartition("}")[2].lower()


def sample(home_url: str, urls: Iterable[str], sample_size: int) -> list[str]:
    """Determinističko uzorkovanje po §4.4.

    Grupisanje po prvom segmentu putanje je važno: leksikografski prvih 8 URL-ova
    daje osam postova iz bloga i propusti da su stranice usluga sve iste.

    Bez fiksnog redosleda isti sajt u dva prolaza daje različite nalaze i nijedan
    test nema smisla (§15, zamka 5) — zato nigde nema `random`.
    """
    home = normalize(home_url)
    picked = [home] if home else []
    remaining = max(sample_size - len(picked), 0)
    if remaining == 0:
        return picked

    groups: dict[str, set[str]] = defaultdict(set)
    for url in urls:
        canonical = normalize(url)
        # Sitemap je tuđ sadržaj: strani host iz njega ne troši budžet ovog domena.
        if canonical and canonical != home and same_site(canonical, home_url):
            groups[path_group(canonical)].add(canonical)

    # Grupe: po veličini opadajuće, pa po imenu — da izjednačenje ne zavisi od
    # redosleda ubacivanja. URL-ovi unutar grupe: leksikografski.
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
