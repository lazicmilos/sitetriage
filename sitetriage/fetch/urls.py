"""URL normalization and comparison. Pure: no network, no disk.

Without it `https://d.rs/usluge` and `https://d.rs/usluge/` are not duplicates, although they
are, and the canonical check produces false positives.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_EXACT = frozenset({"fbclid", "gclid", "ref"})
TRACKING_PREFIXES = ("utm_",)
DEFAULT_PORTS = {"http": 80, "https": 443}
_WS = re.compile(r"\s+")


def normalize(url: str | None, base: str | None = None) -> str | None:
    """The canonical form of a URL, or `None` if the URL is not usable.

    `www.` is deliberately **not** stripped: `www` and non-www are different URLs for
    Google, so mixing them is a finding, not noise.
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
    if ":" in host:  # IPv6 literal: `hostname` drops the brackets, and without them the URL does not parse
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
    """The first path segment, the basis for grouping when sampling.

    Grouping matters: the lexicographically first 8 URLs give eight blog posts
    and miss that the service pages are all the same.
    """
    if not url:
        return "/"
    path = urlsplit(url).path.strip("/")
    return f"/{path.split('/')[0]}" if path else "/"


def host_of(url: str | None) -> str | None:
    return urlsplit(url).hostname if url else None


def same_site(a: str | None, b: str | None) -> bool:
    """`www.d.rs` and `d.rs` are the same site *for sampling links*, not for canonical."""
    ha, hb = host_of(a), host_of(b)
    if not ha or not hb:
        return False
    return ha.removeprefix("www.") == hb.removeprefix("www.")


def collapse_ws(text: str | None) -> str | None:
    """`title` and `description` are compared after trimming and collapsing whitespace."""
    if text is None:
        return None
    return _WS.sub(" ", text).strip()
