"""Snapshoti na disku: pisanje pri prolazu, čitanje pri `recheck`-u (§2.2, §12.2).

Snapshoti se **uvek** pišu, i u normalnom radu, ne samo u test režimu. Koštaju par
stotina kilobajta po domenu i kupuju ti testove bez mreže, kalibraciju bez
ponovnog prolaza i dijagnostiku (§2.1).
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from skener.models import BrowserSnapshot, SiteSnapshot, from_dict, to_jsonable

SITE_NAME = "site.json"
BROWSER_NAME = "browser.json"
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def slug(domain: str) -> str:
    """Ime direktorijuma iz domena.

    Domen dolazi iz CSV-a koji piše korisnik i ume da bude pun origin sa portom,
    pa ne sme da ide direktno u putanju — `../` u imenu domena bi pisao van
    izlaznog direktorijuma.
    """
    cleaned = _UNSAFE.sub("_", domain.strip().lower()).strip("._-")
    return cleaned or "nepoznat-domen"


def write_site(directory: Path, snapshot: SiteSnapshot, *, compress: bool = False) -> Path:
    return _write(directory, snapshot.domain, SITE_NAME, snapshot, compress)


def write_browser(directory: Path, snapshot: BrowserSnapshot, *, compress: bool = False) -> Path:
    return _write(directory, snapshot.domain, BROWSER_NAME, snapshot, compress)


def _write(directory: Path, domain: str, name: str, payload: Any, compress: bool) -> Path:
    target = Path(directory) / slug(domain)
    target.mkdir(parents=True, exist_ok=True)
    text = json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)
    path = target / (f"{name}.gz" if compress else name)
    if compress:
        path.write_bytes(gzip.compress(text.encode("utf-8")))
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(raw.decode("utf-8"))


def _find(folder: Path, name: str) -> Path | None:
    for candidate in (folder / name, folder / f"{name}.gz"):
        if candidate.is_file():
            return candidate
    return None


def read_all(directory: Path) -> Iterator[tuple[SiteSnapshot, BrowserSnapshot | None]]:
    """Čita svaki poddirektorijum; gzipovani i obični fajlovi rade isto."""
    for folder in sorted(Path(directory).iterdir()):
        if not folder.is_dir():
            continue
        site_path = _find(folder, SITE_NAME)
        if site_path is None:
            continue
        site = from_dict(SiteSnapshot, _read_json(site_path))
        browser_path = _find(folder, BROWSER_NAME)
        browser = from_dict(BrowserSnapshot, _read_json(browser_path)) if browser_path else None
        yield site, browser
