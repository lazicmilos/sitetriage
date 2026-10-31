"""Which addresses the tool may open (ADR-006). Pure: no network and no disk.

The scanner opens addresses given by the user. In a web application that means someone can type
`localhost`, `10.0.0.5` or `169.254.169.254` and look at the server from the inside (SSRF). So
only a global unicast address is allowed, except for the `host:port` pairs that the configuration
lists explicitly in `[net] allowed_private`. There is no global switch that turns the protection off.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

Allowlist = frozenset[tuple[str, int]]

# A label that is a number in decimal, octal or hex notation (`127`, `0177`, `0x7f`).
NUMERIC_LABEL = re.compile(r"[0-9]+|0x[0-9a-f]*")


class BlockedAddress(Exception):
    """The address is not public. The domain is `failed`: the site may work, we chose not to open it."""


def is_public(ip: str) -> bool:
    """A global unicast address. IPv4 mapped into IPv6 (`::ffff:127.0.0.1`) is judged as IPv4."""
    address = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def parse_allowed(entries: Iterable[str]) -> Allowlist:
    """`["127.0.0.1:8123", "[::1]:8080"]` → {("127.0.0.1", 8123), ("::1", 8080)}."""
    allowed = set()
    for entry in entries:
        parts = urlsplit(f"//{entry}")
        try:
            port = parts.port
        except ValueError:
            port = None
        if not parts.hostname or port is None or parts.username is not None or parts.path:
            raise ValueError(f"{entry!r} is not of the form host:port")
        allowed.add((parts.hostname.lower(), port))
    return frozenset(allowed)


def allowlist(config: dict[str, Any]) -> Allowlist:
    return parse_allowed(config.get("net", {}).get("allowed_private", []))


def may_connect(ip: str, host: str, port: int, allowed: Allowlist) -> bool:
    return is_public(ip) or (host.lower(), port) in allowed or (ip, port) in allowed


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def looks_like_ipv4(host: str) -> bool:
    """A name whose last label is a number, e.g. `0177.0.0.1`, `127.1` or `2130706433`.

    A browser reads such a name as an IPv4 address in octal, hex or shortened notation (the
    WHATWG URL rule "ends in a number"), while `ipaddress` and httpx do not. What it means depends
    on who parses it, and no real domain ends in a number, so it is treated as an IP address.
    """
    labels = host.lower().removesuffix(".").split(".")
    return bool(NUMERIC_LABEL.fullmatch(labels[-1]))


def input_problem(domain: str, allowed: Allowlist) -> str | None:
    """Why a domain from the list is not opened, or `None`.

    An IP address, a user name or a port in the domain bypass the name that is checked, so they
    are refused, except when the `host:port` is explicitly allowed.
    """
    parts = urlsplit(domain if "://" in domain else f"//{domain}")
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return "the port in the domain is not a number"
    if parts.username is not None:
        return "a domain with a user name is not opened"
    default_port = 80 if parts.scheme == "http" else 443
    if (host, port or default_port) in allowed:
        return None
    if port is not None:
        return "a domain with a port is not opened unless it is explicitly allowed"
    if is_ip(host) or looks_like_ipv4(host):
        return "an IP address instead of a domain is not opened unless it is explicitly allowed"
    return None
