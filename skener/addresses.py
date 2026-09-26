"""Koje adrese alat sme da otvori (ADR-006). Čisto: bez mreže i bez diska.

Skener otvara adrese koje zada korisnik. U web aplikaciji to znači da neko upiše
`localhost`, `10.0.0.5` ili `169.254.169.254` i pregleda server iznutra (SSRF). Zato je
dozvoljena samo globalna unicast adresa, osim `host:port` parova koje konfiguracija
izričito navodi u `[net] allowed_private`. Opšti prekidač koji isključuje zaštitu ne postoji.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

Allowlist = frozenset[tuple[str, int]]


class BlockedAddress(Exception):
    """Adresa nije javna. Domen je `failed`: sajt možda radi, samo ga namerno nismo otvorili."""


def is_public(ip: str) -> bool:
    """Globalna unicast adresa. IPv4 upakovan u IPv6 (`::ffff:127.0.0.1`) sudi se kao IPv4."""
    adresa = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(adresa, ipaddress.IPv6Address) and adresa.ipv4_mapped is not None:
        adresa = adresa.ipv4_mapped
    return adresa.is_global and not adresa.is_multicast


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
            raise ValueError(f"{entry!r} nije oblika host:port")
        allowed.add((parts.hostname.lower(), port))
    return frozenset(allowed)


def allowlist(config: dict[str, Any]) -> Allowlist:
    return parse_allowed(config.get("net", {}).get("allowed_private", []))


def may_connect(ip: str, host: str, port: int, allowed: Allowlist) -> bool:
    return is_public(ip) or (host.lower(), port) in allowed or (ip, port) in allowed


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def input_problem(domain: str, allowed: Allowlist) -> str | None:
    """Zašto se domen iz liste ne otvara, ili `None`.

    IP adresa, korisničko ime i port u domenu zaobilaze ime koje se proverava, pa se
    odbijaju, osim kad je `host:port` izričito dozvoljen.
    """
    parts = urlsplit(domain if "://" in domain else f"//{domain}")
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return "port u domenu nije broj"
    if parts.username is not None:
        return "domen sa korisničkim imenom se ne otvara"
    podrazumevani = 80 if parts.scheme == "http" else 443
    if (host, port or podrazumevani) in allowed:
        return None
    if port is not None:
        return "domen sa portom se ne otvara, osim kad je izričito dozvoljen"
    if _is_ip(host):
        return "IP adresa umesto domena se ne otvara, osim kad je izričito dozvoljena"
    return None
