"""`robots.txt`: parsiranje i poštovanje (§4.3).

Parsiranje je čisto i testira se bez mreže; dohvatanje radi `fetch.http`.

Alat koji istim dahom prijavljuje da sajt nema `robots.txt` i ignoriše ga kad ga
ima je alat kome ne možeš da veruješ (§15, zamka 7).
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RobotsRules:
    """Pravila iz `User-agent: *` sekcije, plus globalne `Sitemap:` direktive."""

    disallow: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()
    crawl_delay: float | None = None
    sitemaps: tuple[str, ...] = field(default=())


def parse(body: str | None) -> RobotsRules:
    """Čita `User-agent: *` sekciju. Pun RFC nije potreban (§4.3)."""
    if not body:
        return RobotsRules()

    disallow: list[str] = []
    allow: list[str] = []
    sitemaps: list[str] = []
    crawl_delay: float | None = None
    in_star_group = False
    # Uzastopni `User-agent` redovi čine jednu grupu; prvo pravilo je zatvara.
    group_open = False

    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "sitemap":
            if value:
                sitemaps.append(value)
            continue

        if field_name == "user-agent":
            if group_open:  # nova grupa počinje posle pravila
                in_star_group = False
                group_open = False
            in_star_group = in_star_group or value == "*"
            continue

        group_open = True
        if not in_star_group:
            continue
        if field_name == "disallow" and value:
            disallow.append(value)
        elif field_name == "allow" and value:
            allow.append(value)
        elif field_name == "crawl-delay":
            with contextlib.suppress(ValueError):
                crawl_delay = float(value.replace(",", "."))

    return RobotsRules(tuple(disallow), tuple(allow), crawl_delay, tuple(sitemaps))


def allows(rules: RobotsRules, url_or_path: str) -> bool:
    """Tačno: najduže poklapanje pobeđuje, `Allow` nadjačava `Disallow`.

    Spec traži samo prefiksno poklapanje sa `*` i `$`, ali `Allow` sa najdužim
    poklapanjem košta tri reda i sprečava da izbacimo iz uzorka putanje koje sajt
    izričito dozvoljava unutar zabranjenog prefiksa.
    """
    path = _path_of(url_or_path)
    longest_disallow = _longest_match(rules.disallow, path)
    longest_allow = _longest_match(rules.allow, path)
    if longest_disallow is None:
        return True
    return longest_allow is not None and longest_allow >= longest_disallow


def _path_of(url_or_path: str) -> str:
    if "://" in url_or_path:
        parts = urlsplit(url_or_path)
        return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return url_or_path or "/"


def _longest_match(patterns: tuple[str, ...], path: str) -> int | None:
    best: int | None = None
    for pattern in patterns:
        if _matches(pattern, path):
            length = len(pattern.rstrip("$"))
            best = length if best is None else max(best, length)
    return best


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(f"^{regex}{'$' if anchored else ''}").match(path) is not None
