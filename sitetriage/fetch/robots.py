"""`robots.txt`: parsing and obeying it.

Parsing is pure and is tested without a network; `fetch.http` does the fetching.

A tool that reports in the same breath that a site has no `robots.txt` and ignores it when it
has one is a tool you cannot trust.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RobotsRules:
    """Rules from the `User-agent: *` section, plus the global `Sitemap:` directives."""

    disallow: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()
    crawl_delay: float | None = None
    sitemaps: tuple[str, ...] = field(default=())


def parse(body: str | None) -> RobotsRules:
    """Reads the `User-agent: *` section. The full RFC is not needed."""
    if not body:
        return RobotsRules()

    disallow: list[str] = []
    allow: list[str] = []
    sitemaps: list[str] = []
    crawl_delay: float | None = None
    in_star_group = False
    # Consecutive `User-agent` lines form one group; the first rule closes it.
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
            if group_open:  # a new group starts after a rule
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
    """Exact matching: the longest match wins, and `Allow` overrides `Disallow`.

    The specification asks only for prefix matching with `*` and `$`, but `Allow` with the longest
    match costs three lines and keeps us from dropping from the sample paths that the site
    explicitly allows inside a disallowed prefix.
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
