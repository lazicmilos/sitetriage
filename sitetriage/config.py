"""Loads thresholds from TOML. It reads the disk and does nothing else.

Every threshold, multiplier and constant lives in TOML, not in code. The default config,
`sitetriage.toml`, ships inside the package. `--config` is **merged over** it, so a partial
user configuration keeps all the other thresholds.

A profile (`sitetriage/profiles/<name>.toml`, also package data) sits between the two: package
defaults → profile → user `--config` (ADR-023). It is chosen with `--profile NAME` or with a
top-level `profile = "NAME"` in the user config; the flag wins.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tomllib
import unicodedata
from importlib import resources
from pathlib import Path
from typing import Any

from sitetriage import __version__
from sitetriage.addresses import parse_allowed
from sitetriage.models import CATEGORIES, CONTENT_LANGUAGES, INDUSTRIES, REPORT_LANGUAGES

CONFIG_NAME = "sitetriage.toml"
PROFILES_DIR = "profiles"

# These do not change the result, so they stay out of the config digest: who scans, how much in
# parallel and where the browser is. Two runs with the same digest have the same thresholds,
# multipliers and points.
NOT_IN_DIGEST = (
    "operator",
    # The name of the profile is not a value: what the profile changes is already in the digest.
    "profile",
    "http.concurrency",
    "http.per_host_concurrency",
    "http.domain_concurrency",
    "http.user_agent",
    # The language changes the sentences, not the findings or the scores.
    "report.lang",
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
    """The defaults layer: always the `sitetriage.toml` in the package.

    A `sitetriage.toml` in the working directory is never read implicitly: it is a user file like
    any other and counts only when passed with `--config`, which merges it over these defaults
    (BUG-04). In a repository clone or an editable install the package file is the repository's
    `sitetriage/sitetriage.toml`, so calibrating the defaults there still works.
    """
    packaged = _packaged_config_path()
    if packaged.is_file():
        return packaged
    raise ConfigError(
        f"{CONFIG_NAME} was not found in the package ({packaged.parent}). "
        f"Reinstall SiteTriage; the default config ships with it, and --config is merged over it."
    )


def available_profiles() -> list[str]:
    """Names of the profiles that ship inside the package (`sitetriage/profiles/<name>.toml`)."""
    folder = resources.files("sitetriage").joinpath(PROFILES_DIR)
    if not folder.is_dir():
        return []
    return sorted(item.name.removesuffix(".toml") for item in folder.iterdir() if item.name.endswith(".toml"))


def profile_path(name: str) -> Path:
    """The packaged file of profile `name`; an unknown name fails and lists the available ones."""
    names = available_profiles()
    # Comparing with the list also keeps a name like `../x` from reading a file outside the package.
    if name not in names:
        raise ConfigError(f"unknown profile {name!r}; available profiles: {', '.join(names) or 'none'}")
    return Path(str(resources.files("sitetriage").joinpath(PROFILES_DIR).joinpath(f"{name}.toml")))


def load_config(path: str | Path | None = None, *, profile: str | None = None) -> dict[str, Any]:
    """Package defaults → profile → user `--config`, then validation of the merged result.

    `profile` is the `--profile` flag: when it is given (even empty, which means "no profile"), it
    wins over `profile` in the user config. The chosen name is stored under `profile`, `""` = none.
    """
    cfg = _read(default_config_path())
    reference = copy.deepcopy(cfg)
    user: dict[str, Any] = {}
    if path is not None:
        user_path = Path(path)
        if not user_path.is_file():
            raise ConfigError(f"configuration file does not exist: {user_path}")
        user = _read(user_path)
    name = profile if profile is not None else user.get("profile", cfg.get("profile", ""))
    if not isinstance(name, str):
        raise ConfigError(f"profile must be the name of a profile as a string, got {name!r}")
    if name:
        layer = _read(profile_path(name))
        if "profile" in layer:
            raise ConfigError(f"profile {name!r}: a profile cannot choose another profile")
        _merge(cfg, layer)
    _merge(cfg, user)
    cfg["profile"] = name
    _validate(cfg, reference)
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

# A speed or a timeout of 0 fails every request or divides by zero in the sentences, and Chromium
# reads a speed of 0 as "no limit". Points of 0 or less and a ratio of 0 or less invert or empty
# the ranking without a word (BUG-06).
POSITIVE_NUMBERS = (
    "http.timeout_connect_s",
    "http.timeout_read_s",
    "http.timeout_total_s",
    "http.max_seconds_per_domain",
    "browser.timeout_s",
    "browser.drain_timeout_s",
    "browser.max_seconds_per_domain",
    "network_profile.download_mbps",
    "network_profile.upload_mbps",
    "network_profile.probe_max_s",
    "network_profile.min_link_ratio",
    "thresholds.perf.image_ratio",
    *(f"severity_points.{severity}" for severity in ("critical", "high", "medium", "low")),
)

# Shares of something: above 1 a threshold can never be reached.
SHARES = (
    "thresholds.seo.canonical_share.high",
    "thresholds.seo.canonical_share.critical",
    "thresholds.i18n.cyrillic_ratio",
    "thresholds.i18n.diacritic_ratio",
    "thresholds.a11y.missing_ratio",
    "thresholds.a11y.high_ratio",
    "thresholds.soft404.text_similarity",
)

# Severity tiers of one measurement: a higher severity needs a strictly larger value.
TIERS = (
    "thresholds.seo.canonical_share",
    "thresholds.perf.page_weight_mb",
    "thresholds.perf.request_count",
    "thresholds.perf.load_ms",
)
TIER_ORDER = ("medium", "high", "critical")

# A quantity in a unit may be fractional (2.5 s) even where the default is a whole number; a count
# (pages, files, points) may not.
UNIT_SUFFIXES = ("_s", "_ms", "_kb", "_mb", "_mbps")

# Checked by their own rule, with a message that says more than "must be a list".
TYPED_ELSEWHERE = ("thresholds.i18n.content_languages", "net.allowed_private")


def _renamed(cfg: dict[str, Any]) -> None:
    for old, (new, keys) in RENAMED_SECTIONS.items():
        if old in cfg:
            pairs = ", ".join(f"{k} → {v}" for k, v in keys.items())
            raise ConfigError(f"[{old}] was renamed to [{new}] in SiteTriage 3.0 ({pairs}); see {ADR_012}")


def _is_number(value: Any) -> bool:
    # bool is a subclass of int, but `true` is never meant as 1.
    return isinstance(value, int | float) and not isinstance(value, bool)


def _fractional(dotted: str) -> bool:
    return "seconds" in dotted or any(part.endswith(UNIT_SUFFIXES) for part in dotted.split("."))


def _type_error(dotted: str, default: Any, value: Any) -> str | None:
    """Why `value` cannot stand where the packaged default is `default`; None if it can."""
    if isinstance(default, bool):
        return None if isinstance(value, bool) else "true or false"
    if isinstance(default, int | float):
        whole = isinstance(default, int) and not _fractional(dotted)
        if not _is_number(value) or (whole and not isinstance(value, int)):
            return "an integer" if whole else "a number"
        return None if math.isfinite(value) else "a finite number"
    if isinstance(default, str):
        return None if isinstance(value, str) else "a string"
    if isinstance(default, list):
        if not isinstance(value, list):
            return "a list"
        for item in value if default else ():
            if (why := _type_error(dotted, default[0], item)) is not None:
                return f"a list of items that are each {why}"
        return None
    return None if isinstance(value, dict) else "a table"


def _leaves(reference: dict[str, Any], cfg: dict[str, Any], prefix: str = ""):
    """(dotted key, packaged default, value) for every key the merged config shares with the defaults."""
    for key, default in reference.items():
        if key not in cfg:
            continue
        dotted, value = f"{prefix}{key}", cfg[key]
        if isinstance(default, dict) and isinstance(value, dict):
            yield from _leaves(default, value, f"{dotted}.")
        else:
            yield dotted, default, value


def _check_types(reference: dict[str, Any], cfg: dict[str, Any]) -> None:
    """Every value has the type of its packaged default: a run must not crash on it halfway (BUG-06)."""
    for dotted, default, value in _leaves(reference, cfg):
        if dotted in TYPED_ELSEWHERE:
            continue
        if (why := _type_error(dotted, default, value)) is not None:
            raise ConfigError(f"{dotted} must be {why}, got {value!r}")


def _check_not_negative(reference: dict[str, Any], cfg: dict[str, Any]) -> None:
    """No count, size, time, ratio or multiplier in the config means anything below zero."""
    for dotted, _default, value in _leaves(reference, cfg):
        for item in value if isinstance(value, list) else [value]:
            if _is_number(item) and item < 0:
                raise ConfigError(f"{dotted} must be ≥ 0, got {value!r}")


def _integer_at_least(cfg: dict[str, Any], dotted: str, minimum: int, why: str = "") -> None:
    value = get(cfg, dotted)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{dotted} must be an integer ≥ {minimum}{why}, got {value!r}")


def _check_ranges(cfg: dict[str, Any]) -> None:
    for dotted in POSITIVE_INTS:
        _integer_at_least(cfg, dotted, 1)
    _integer_at_least(cfg, "browser.light_concurrency", 0)
    # The home page is always the first page of the sample; without one more page every check
    # that compares pages has nothing to compare.
    _integer_at_least(cfg, "sitemap.sample_size", 2, " (the home page and at least one more page)")
    for dotted in POSITIVE_NUMBERS:
        value = get(cfg, dotted)
        if not _is_number(value) or value <= 0:
            raise ConfigError(f"{dotted} must be > 0, got {value!r}")
    for dotted in SHARES:
        value = get(cfg, dotted)
        if not _is_number(value) or not 0 < value <= 1:
            raise ConfigError(f"{dotted} must be a share > 0 and ≤ 1, got {value!r}")
    for dotted in TIERS:
        tiers = get(cfg, dotted)
        values = [tiers[tier] for tier in TIER_ORDER if tier in tiers]
        if any(low >= high for low, high in zip(values, values[1:], strict=False)):
            order = " < ".join(tier for tier in TIER_ORDER if tier in tiers)
            raise ConfigError(f"{dotted} must grow with severity ({order}), got {tiers!r}")
    # A pause towards the same host, drawn between the two numbers (politeness, ADR-006).
    delay = get(cfg, "http.delay_ms")
    pair = isinstance(delay, list) and len(delay) == 2 and all(map(_is_number, delay))
    if not pair or not 0 <= delay[0] <= delay[1]:
        raise ConfigError(f"http.delay_ms must be two numbers [min, max] with 0 ≤ min ≤ max, got {delay!r}")


def _validate(cfg: dict[str, Any], reference: dict[str, Any] | None = None) -> None:
    """`reference` is the packaged defaults the types are checked against; read when not given."""
    _renamed(cfg)
    if reference is None:
        reference = _read(default_config_path())
    _check_types(reference, cfg)
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
    _check_ranges(cfg)
    languages = get(cfg, "thresholds.i18n.content_languages")
    if not isinstance(languages, list) or any(code not in CONTENT_LANGUAGES for code in languages):
        raise ConfigError(
            f"thresholds.i18n.content_languages must be a list of languages with a detector "
            f"({', '.join(CONTENT_LANGUAGES)}), got {languages!r}; a profile such as `rs` sets it"
        )
    lang = get(cfg, "report.lang")
    if lang not in REPORT_LANGUAGES:
        raise ConfigError(f"report.lang must be one of {', '.join(REPORT_LANGUAGES)}, got {lang!r}")
    allowed = get(cfg, "net.allowed_private")
    if not isinstance(allowed, list):
        raise ConfigError(f"net.allowed_private must be a list of \"host:port\" pairs, got {allowed!r}")
    try:
        parse_allowed(allowed)
    except ValueError as exc:
        raise ConfigError(f"net.allowed_private: {exc}") from None
    _check_not_negative(reference, cfg)
