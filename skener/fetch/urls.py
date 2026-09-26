"""Normalizacija i poređenje URL-ova (§4.5). Čista: bez mreže, bez diska.

Bez ovoga `https://d.rs/usluge` i `https://d.rs/usluge/` nisu duplikat, a jesu —
i provera canonical-a proizvodi lažne pozitive (§15, zamka 4).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_EXACT = frozenset({"fbclid", "gclid", "ref"})
TRACKING_PREFIXES = ("utm_",)
DEFAULT_PORTS = {"http": 80, "https": 443}
_WS = re.compile(r"\s+")


def normalize(url: str | None, base: str | None = None) -> str | None:
    """Kanonski oblik URL-a, ili `None` ako adresa nije upotrebljiva.

    `www.` se namerno **ne** uklanja: `www` i non-www jesu različite adrese za
    Google, pa je njihovo mešanje nalaz, a ne šum (§4.5, tačka 7).
    """
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith("#"):
        return None
    if base:
        url = urljoin(base, url)

    parts = urlsplit(url)
    if parts.scheme not in DEFAULT_PORTS or not parts.hostname:
        return None

    host = parts.hostname.rstrip(".")
    if ":" in host:  # IPv6 literal: `hostname` skida zagrade, a bez njih URL ne parsira
        host = f"[{host}]"
    if parts.port and parts.port != DEFAULT_PORTS[parts.scheme]:
        host = f"{host}:{parts.port}"

    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"

    query = urlencode(sorted(_keep_params(parts.query)))
    return urlunsplit((parts.scheme, host, path, query, ""))


def _keep_params(query: str) -> list[tuple[str, str]]:
    return [
        (k, v)
        for k, v in parse_qsl(query, keep_blank_values=True)
        if k.lower() not in TRACKING_EXACT and not k.lower().startswith(TRACKING_PREFIXES)
    ]


def path_group(url: str | None) -> str:
    """Prvi segment putanje — osnova grupisanja pri uzorkovanju (§4.4).

    Grupisanje je važno: leksikografski prvih 8 URL-ova daje osam blog postova
    i propusti da su stranice usluga sve iste.
    """
    if not url:
        return "/"
    path = urlsplit(url).path.strip("/")
    return f"/{path.split('/')[0]}" if path else "/"


def host_of(url: str | None) -> str | None:
    return urlsplit(url).hostname if url else None


def same_site(a: str | None, b: str | None) -> bool:
    """`www.d.rs` i `d.rs` su isti sajt *za uzorkovanje linkova* — ne za canonical."""
    ha, hb = host_of(a), host_of(b)
    if not ha or not hb:
        return False
    return ha.removeprefix("www.") == hb.removeprefix("www.")


def collapse_ws(text: str | None) -> str | None:
    """Poređenje `title` i `description` ide nad trim + sažetim razmacima (§4.5)."""
    if text is None:
        return None
    return _WS.sub(" ", text).strip()
