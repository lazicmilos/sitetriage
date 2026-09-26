"""Učitavanje pragova iz TOML-a (§11.2). Čita disk, ništa drugo ne radi.

`skener.toml` iz repoa je podrazumevana konfiguracija. `--config` se **spaja
preko** nje, pa parcijalna korisnička konfiguracija ne gubi ostale pragove.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tomllib
import unicodedata
from pathlib import Path
from typing import Any

from skener import __version__
from skener.addresses import parse_allowed
from skener.models import CATEGORIES, INDUSTRIES

CONFIG_NAME = "skener.toml"

# Ne menjaju rezultat, pa ne ulaze u otisak konfiguracije: ko skenira, koliko paralelno i
# gde je browser. Dva prolaza sa istim otiskom imaju iste pragove, množioce i bodove.
BEZ_UTICAJA_NA_REZULTAT = (
    "identitet",
    "http.concurrency",
    "http.per_host_concurrency",
    "http.domain_concurrency",
    "http.user_agent",
    "browser.concurrency",
    "browser.executable_path",
)

# Srpska ćirilica i đ nemaju ASCII rastavljanje, pa se presipaju ručno; š, č, ć i ž
# posle toga rastavlja NFKD. HTTP zaglavlje sme da nosi samo ASCII.
_U_LATINICU = str.maketrans(
    {
        **dict(zip("абвгдежзијклмнопрстћуфхцчш", "abvgdezzijklmnoprstcufhccs", strict=True)),
        **dict(zip("АБВГДЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ", "ABVGDEZZIJKLMNOPRSTCUFHCCS", strict=True)),
        "ђ": "dj", "Ђ": "Dj", "љ": "lj", "Љ": "Lj", "њ": "nj", "Њ": "Nj", "џ": "dz", "Џ": "Dz",
        "đ": "dj", "Đ": "Dj",
    }
)


class ConfigError(Exception):
    """Konfiguracija je korisnički ulaz — puca glasno i imenuje ključ."""


def default_config_path() -> Path:
    """Prvo radni direktorijum, pa koren repoa pored paketa."""
    for candidate in (Path.cwd() / CONFIG_NAME, Path(__file__).resolve().parent.parent / CONFIG_NAME):
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"{CONFIG_NAME} nije nađen ni u {Path.cwd()} ni pored paketa. "
        f"Pokreni alat iz korena repoa ili prosledi --config PUTANJA."
    )


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = _read(default_config_path())
    if path is not None:
        user_path = Path(path)
        if not user_path.is_file():
            raise ConfigError(f"konfiguracija ne postoji: {user_path}")
        if user_path.resolve() != default_config_path().resolve():
            _merge(cfg, _read(user_path))
    _validate(cfg)
    return cfg


def get(cfg: dict[str, Any], dotted: str) -> Any:
    """`get(cfg, "thresholds.perf.image_ratio")` — puca ako ključ ne postoji."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"nedostaje ključ u konfiguraciji: {dotted}")
        node = node[part]
    return node


def _ascii(tekst: str) -> str:
    """Ime koje kupac upiše kako mu je prirodno → ono što HTTP zaglavlje sme da nosi.

    Srpska slova se presipaju, ostalo (crte, emodžiji) otpada, a razmaci i novi redovi
    se sažimaju u jedan razmak — novi red bi u zahtevu započeo novo zaglavlje.
    """
    rastavljeno = unicodedata.normalize("NFKD", tekst.translate(_U_LATINICU))
    return " ".join(rastavljeno.encode("ascii", "ignore").decode("ascii").split())


def user_agent(cfg: dict[str, Any]) -> str:
    """User-Agent koji predstavlja operatera — onog ko pokreće skeniranje.

    Administrator sajta u svom logu vidi ko ga skenira i kako da ga kontaktira. Alat
    se prodaje, pa to mora biti kupac, ne autor alata; bez oba podatka nema
    skeniranja. `SKENER_NAZIV` i `SKENER_KONTAKT` imaju prednost nad fajlom (Docker).
    """
    naziv = _ascii(os.environ.get("SKENER_NAZIV") or get(cfg, "identitet.naziv") or "")
    kontakt = _ascii(os.environ.get("SKENER_KONTAKT") or get(cfg, "identitet.kontakt") or "")
    if not naziv or not kontakt:
        raise ConfigError(
            "[identitet] naziv i kontakt nisu postavljeni. Administrator sajta mora da zna ko ga "
            "skenira i kako da ga kontaktira: upiši ih u svoj --config fajl ili postavi "
            "SKENER_NAZIV i SKENER_KONTAKT."
        )
    return get(cfg, "http.user_agent").format(verzija=__version__, naziv=naziv, kontakt=kontakt)


def digest(cfg: dict[str, Any]) -> str:
    """sha256 kanonskog JSON-a konfiguracije koja utiče na rezultat.

    `diff` po njemu zna da li je razlika između dva prolaza od sajta ili od pragova.
    """
    kopija = copy.deepcopy(cfg)
    for dotted in BEZ_UTICAJA_NA_REZULTAT:
        *put, kljuc = dotted.split(".")
        sekcija = kopija
        for deo in put:
            sekcija = sekcija.get(deo, {})
        sekcija.pop(kljuc, None)
    kanonski = json.dumps(kopija, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(kanonski.encode("utf-8")).hexdigest()


def multiplier(cfg: dict[str, Any], industry: str, category: str) -> float:
    """Množilac po delatnosti (§9.2); nepoznata delatnost pada na `ostalo`."""
    table = cfg["industry_multipliers"]
    return float(table.get(industry, table["ostalo"])[category])


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: neispravan TOML — {exc}") from exc


def _merge(base: dict[str, Any], over: dict[str, Any]) -> None:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


# Nula mesta u semaforu ne pušta nikog: prolaz stoji zauvek, bez ijedne poruke (BUG-011).
POZITIVNI_CELI = (
    "http.concurrency",
    "http.domain_concurrency",
    "browser.concurrency",
    "http.max_requests_per_domain",
)


def _validate(cfg: dict[str, Any]) -> None:
    for severity in ("critical", "high", "medium", "low"):
        if severity not in cfg.get("severity_points", {}):
            raise ConfigError(f"severity_points.{severity} nedostaje")
    table = cfg.get("industry_multipliers", {})
    for industry in INDUSTRIES:
        if industry not in table:
            raise ConfigError(f"industry_multipliers.{industry} nedostaje")
        for category in CATEGORIES:
            if category not in table[industry]:
                raise ConfigError(f"industry_multipliers.{industry}.{category} nedostaje")
    for dotted in POZITIVNI_CELI:
        value = get(cfg, dotted)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError(f"{dotted} mora biti ceo broj ≥ 1, a jeste {value!r}")
    seconds = get(cfg, "http.max_seconds_per_domain")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds <= 0:
        raise ConfigError(f"http.max_seconds_per_domain mora biti > 0, a jeste {seconds!r}")
    allowed = get(cfg, "net.allowed_private")
    if not isinstance(allowed, list):
        raise ConfigError(f"net.allowed_private mora biti lista \"host:port\" parova, a jeste {allowed!r}")
    try:
        parse_allowed(allowed)
    except ValueError as exc:
        raise ConfigError(f"net.allowed_private: {exc}") from None
