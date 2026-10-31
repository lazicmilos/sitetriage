"""Loads thresholds from TOML. It reads the disk and does nothing else.

Every threshold, multiplier and constant lives in TOML, not in code. The default config,
`sitetriage.toml`, ships inside the package. `--config` is **merged over** it, so a partial
user configuration keeps all the other thresholds.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tomllib
import unicodedata
from importlib import resources
from pathlib import Path
from typing import Any

from sitetriage import __version__
from sitetriage.addresses import parse_allowed
from sitetriage.models import CATEGORIES, INDUSTRIES

CONFIG_NAME = "sitetriage.toml"

# These do not change the result, so they stay out of the config digest: who scans, how much in
# parallel and where the browser is. Two runs with the same digest have the same thresholds,
# multipliers and points.
NOT_IN_DIGEST = (
    "operator",
    "http.concurrency",
    "http.per_host_concurrency",
    "http.domain_concurrency",
    "http.user_agent",
    "browser.concurrency",
    "browser.light_concurrency",
    "browser.executable_path",
)

# Serbian Cyrillic and đ have no ASCII decomposition, so they are transliterated by hand; NFKD
# then decomposes š, č, ć and ž. An HTTP header may carry only ASCII.
_TO_LATIN = str.maketrans(
    {
        **dict(zip("абвгдежзијклмнопрстћуфхцчш", "abvgdezzijklmnoprstcufhccs", strict=True)),
        **dict(zip("АБВГДЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ", "ABVGDEZZIJKLMNOPRSTCUFHCCS", strict=True)),
        "ђ": "dj", "Ђ": "Dj", "љ": "lj", "Љ": "Lj", "њ": "nj", "Њ": "Nj", "џ": "dz", "Џ": "Dz",
        "đ": "dj", "Đ": "Dj",
    }
)


# Who is scanning, from the environment; takes precedence over `[operator]` (Docker, CI).
ENV_OPERATOR_NAME = "SITETRIAGE_OPERATOR_NAME"
ENV_OPERATOR_CONTACT = "SITETRIAGE_OPERATOR_CONTACT"

# Sections renamed in 3.0 (ADR-012). A user config that still uses one would be merged and
# silently ignored, so it fails loudly and names the new keys.
RENAMED_SECTIONS = {
    "identitet": ("operator", {"naziv": "name", "kontakt": "contact", "izuzeti": "exclude_file"}),
}
ADR_012 = "docs/adr/ADR-012-english-public-interface.md"


class ConfigError(Exception):
    """The configuration is user input: it fails loudly and names the key."""


def _packaged_config_path() -> Path:
    """The default config that ships inside the package (package data, see pyproject.toml)."""
    # An installed package is unpacked on disk, so the resource is a real file.
    return Path(str(resources.files("sitetriage").joinpath(CONFIG_NAME)))


def default_config_path() -> Path:
    """A full `sitetriage.toml` in the working directory first, then the one in the package."""
    packaged = _packaged_config_path()
    for candidate in (Path.cwd() / CONFIG_NAME, packaged):
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"{CONFIG_NAME} was found neither in {Path.cwd()} nor in the package ({packaged.parent}). "
        f"Reinstall SiteTriage; the default config ships with it, and --config is merged over it."
    )


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = _read(default_config_path())
    if path is not None:
        user_path = Path(path)
        if not user_path.is_file():
            raise ConfigError(f"configuration file does not exist: {user_path}")
        if user_path.resolve() != default_config_path().resolve():
            _merge(cfg, _read(user_path))
    _validate(cfg)
    return cfg


def get(cfg: dict[str, Any], dotted: str) -> Any:
    """`get(cfg, "thresholds.perf.image_ratio")`; fails if the key does not exist."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"missing configuration key: {dotted}")
        node = node[part]
    return node


def _ascii(text: str) -> str:
    """A name the operator writes however comes naturally → what an HTTP header may carry.

    Serbian letters are transliterated, everything else (dashes, emoji) is dropped, and spaces
    and newlines collapse into one space: a newline would start a new header in the request.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_TO_LATIN))
    return " ".join(decomposed.encode("ascii", "ignore").decode("ascii").split())


def user_agent(cfg: dict[str, Any]) -> str:
    """The User-Agent that represents the operator, whoever runs the scan.

    The site administrator sees in their log who is scanning them and how to reach them. That
    is the operator who started the tool, not the author of the tool; without both values
    there is no scanning. `SITETRIAGE_OPERATOR_NAME` and `SITETRIAGE_OPERATOR_CONTACT` take
    precedence over the file (Docker).
    """
    name = _ascii(os.environ.get(ENV_OPERATOR_NAME) or get(cfg, "operator.name") or "")
    contact = _ascii(os.environ.get(ENV_OPERATOR_CONTACT) or get(cfg, "operator.contact") or "")
    if not name or not contact:
        raise ConfigError(
            "[operator] name and contact are not set. The site administrator must know who is "
            "scanning them and how to reach them: put them in your --config file or set "
            f"{ENV_OPERATOR_NAME} and {ENV_OPERATOR_CONTACT}."
        )
    return get(cfg, "http.user_agent").format(version=__version__, name=name, contact=contact)


def digest(cfg: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of the configuration that affects the result.

    `diff` uses it to tell whether a difference between two runs comes from the site or from
    the thresholds.
    """
    clone = copy.deepcopy(cfg)
    for dotted in NOT_IN_DIGEST:
        *path, key = dotted.split(".")
        section = clone
        for part in path:
            section = section.get(part, {})
        section.pop(key, None)
    canonical = json.dumps(clone, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def multiplier(cfg: dict[str, Any], industry: str, category: str) -> float:
    """Multiplier by industry; an unknown industry falls back to `other`.

    A finding's weight is `severity_points[severity] × industry_multipliers[industry][category]`.
    """
    table = cfg["industry_multipliers"]
    return float(table.get(industry, table["other"])[category])


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc


def _merge(base: dict[str, Any], over: dict[str, Any]) -> None:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


# A semaphore with zero slots lets no one through: the run stalls forever, without a single
# message (BUG-011).
POSITIVE_INTS = (
    "http.concurrency",
    "http.domain_concurrency",
    "browser.concurrency",
    "http.max_requests_per_domain",
    "http.max_body_kb",
    "sitemap.max_kb",
)


def _renamed(cfg: dict[str, Any]) -> None:
    for old, (new, keys) in RENAMED_SECTIONS.items():
        if old in cfg:
            pairs = ", ".join(f"{k} → {v}" for k, v in keys.items())
            raise ConfigError(f"[{old}] was renamed to [{new}] in SiteTriage 3.0 ({pairs}); see {ADR_012}")


def _validate(cfg: dict[str, Any]) -> None:
    _renamed(cfg)
    for severity in ("critical", "high", "medium", "low"):
        if severity not in cfg.get("severity_points", {}):
            raise ConfigError(f"severity_points.{severity} is missing")
    table = cfg.get("industry_multipliers", {})
    # A table for an unknown industry is never used: a user calibration under an old (pre-3.0)
    # name like `restoran` would be lost without a word.
    for industry in table:
        if industry not in INDUSTRIES:
            raise ConfigError(
                f"industry_multipliers.{industry}: unknown industry; known: {', '.join(INDUSTRIES)} "
                f"(renamed in SiteTriage 3.0, see {ADR_012})"
            )
    for industry in INDUSTRIES:
        if industry not in table:
            raise ConfigError(f"industry_multipliers.{industry} is missing")
        for category in CATEGORIES:
            if category not in table[industry]:
                raise ConfigError(f"industry_multipliers.{industry}.{category} is missing")
    for dotted in POSITIVE_INTS:
        value = get(cfg, dotted)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError(f"{dotted} must be an integer ≥ 1, got {value!r}")
    value = get(cfg, "browser.light_concurrency")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"browser.light_concurrency must be an integer ≥ 0, got {value!r}")
    # A speed of 0 divides by zero in the sentences, and Chromium reads it as "no limit".
    for dotted in (
        "http.max_seconds_per_domain",
        "network_profile.download_mbps",
        "network_profile.upload_mbps",
        "network_profile.probe_max_s",
        "network_profile.min_link_ratio",
    ):
        value = get(cfg, dotted)
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ConfigError(f"{dotted} must be > 0, got {value!r}")
    allowed = get(cfg, "net.allowed_private")
    if not isinstance(allowed, list):
        raise ConfigError(f"net.allowed_private must be a list of \"host:port\" pairs, got {allowed!r}")
    try:
        parse_allowed(allowed)
    except ValueError as exc:
        raise ConfigError(f"net.allowed_private: {exc}") from None
