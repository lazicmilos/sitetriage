"""Snapshots on disk: written during a run, read by `recheck`.

Snapshots are **always** written, in normal use too, not only in a test mode. They cost a
few hundred kilobytes per domain and buy you tests without a network, calibration without a
new run, and diagnosis: checks receive a finished snapshot and never touch the network
(CONTRIBUTING, "Architecture rules").
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sitetriage.inputs import InputError
from sitetriage.models import BrowserSnapshot, SiteSnapshot, from_dict, to_jsonable

SITE_NAME = "site.json"
# Industry values before 3.0 (ADR-012). Field names did not change, so a 1.x or 2.x snapshot is
# read as is; only `industry` is mapped, otherwise `recheck` would silently score it as `other`.
LEGACY_INDUSTRIES = {
    "restoran": "restaurant",
    "zdravstvo": "healthcare",
    "institucija": "institution",
    "ostalo": "other",
}
BROWSER_NAME = "browser.json"
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


class SnapshotCollision(ValueError):
    """The folder for a domain already holds the snapshot of another domain."""


def slug(domain: str) -> str:
    """Directory name from a domain: readable, path-safe and different for every domain string.

    The domain comes from a CSV the user writes and can be a full origin with a port, so it
    must not go straight into a path: `../` in a domain name would write outside the output
    directory. Cleaning alone is not injective (`localhost` and `localhost.`, or an origin with
    and without a trailing `/`, clean to the same name), and two domains in one folder means
    `recheck` silently loses one. So whenever cleaning changed anything, the name gets `~` and a
    short hash of the exact domain string. A clean name never contains `~`, and a clean domain
    keeps the name it had in 3.0.0. The same domain always gets the same folder, which level 1
    and level 2 both rely on.
    """
    cleaned = _UNSAFE.sub("_", domain.strip().lower()).strip("._-") or "unknown-domain"
    if cleaned == domain:
        return cleaned
    return f"{cleaned}~{hashlib.sha256(domain.encode('utf-8')).hexdigest()[:8]}"


def write_site(directory: Path, snapshot: SiteSnapshot, *, compress: bool = False) -> Path:
    return _write(directory, snapshot.domain, SITE_NAME, snapshot, compress)


def write_browser(directory: Path, snapshot: BrowserSnapshot, *, compress: bool = False) -> Path:
    return _write(directory, snapshot.domain, BROWSER_NAME, snapshot, compress)


def _write(directory: Path, domain: str, name: str, payload: Any, compress: bool) -> Path:
    target = Path(directory) / slug(domain)
    target.mkdir(parents=True, exist_ok=True)
    _refuse_foreign(target, domain)
    text = json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)
    path = target / (f"{name}.gz" if compress else name)
    if compress:
        path.write_bytes(gzip.compress(text.encode("utf-8")))
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _refuse_foreign(folder: Path, domain: str) -> None:
    """Defence in depth: never overwrite or join the snapshot of another domain in its folder."""
    for name in (SITE_NAME, BROWSER_NAME):
        path = _find(folder, name)
        if path is None:
            continue
        try:
            existing = _read_json(path).get("domain")
        except (OSError, ValueError):
            continue  # a broken file from an interrupted run is simply replaced
        if existing != domain:
            raise SnapshotCollision(f"{folder} already holds the snapshot of {existing!r}, not {domain!r}")


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as exc:  # BadGzipFile is an OSError; a cut-off file is EOFError
            raise InputError(f"{path}: not valid gzip ({exc})") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError
        raise InputError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise InputError(f"{path}: not a snapshot (expected a JSON object, got {type(data).__name__})")
    return data


def _load(cls: Any, path: Path, data: dict[str, Any]) -> Any:
    try:
        return from_dict(cls, data)
    except (TypeError, ValueError, KeyError) as exc:
        raise InputError(f"{path}: not a snapshot ({exc})") from exc


def _migrate_site(data: dict[str, Any]) -> dict[str, Any]:
    industry = data.get("industry")
    if industry in LEGACY_INDUSTRIES:
        data["industry"] = LEGACY_INDUSTRIES[industry]
    return data


def _find(folder: Path, name: str) -> Path | None:
    for candidate in (folder / name, folder / f"{name}.gz"):
        if candidate.is_file():
            return candidate
    return None


def read_all(directory: Path) -> Iterator[tuple[SiteSnapshot, BrowserSnapshot | None]]:
    """Reads every subdirectory; gzipped and plain files work the same.

    A folder that is missing or a snapshot that does not parse is an `InputError` naming the path,
    not a skipped domain: a calibration run must not quietly lose one (BUG-10).
    """
    directory = Path(directory)
    if not directory.exists():
        raise InputError(f"{directory}: the snapshot folder does not exist")
    if not directory.is_dir():
        raise InputError(f"{directory}: is not a folder of snapshots")
    for folder in sorted(directory.iterdir()):
        if not folder.is_dir():
            continue
        site_path = _find(folder, SITE_NAME)
        if site_path is None:
            continue
        site = _load(SiteSnapshot, site_path, _migrate_site(_read_json(site_path)))
        browser_path = _find(folder, BROWSER_NAME)
        browser = _load(BrowserSnapshot, browser_path, _read_json(browser_path)) if browser_path else None
        yield site, browser
