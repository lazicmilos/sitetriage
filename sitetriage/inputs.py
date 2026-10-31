"""Input the user provides: the domain list and other CSV files from Excel.

An input error is an `InputError`, not a `SystemExit`. The CLI and the web worker read the
same input, so the caller decides what to do with the error: the CLI prints it and exits, the
worker returns it to the user. Warnings are returned rather than logged for the same reason.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sitetriage.models import INDUSTRIES, DomainInput


class InputError(ValueError):
    """Input that cannot be processed. The message names the source and, when known, the row number."""


@dataclass
class InputWarning:
    """The input was processed, but with a change the user should see."""

    message: str
    row: int | None = None
    domain: str | None = None


@dataclass
class CsvTable:
    fieldnames: list[str]
    # (row number as Excel shows it, values): the user finds the row by its number
    rows: list[tuple[int, dict[str, str]]]
    header_row: int = 1
    warnings: list[InputWarning] = field(default_factory=list)


def read_excel_csv(data: bytes, source: str) -> CsvTable:
    """CSV as Excel writes it on Windows with Serbian regional settings.

    Without the "CSV UTF-8" option Excel saves in windows-1250, and the Serbian Windows settings
    separate columns with `;`, not with a comma. The row number counts records, not lines in
    the file: a cell with a line break is one row in Excel and two lines in the file.
    """
    warnings: list[InputWarning] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append(InputWarning(f"{source} is not UTF-8, reading it as windows-1250"))
        text = data.decode("cp1250", errors="replace")
    header = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t", key=header.count) if any(c in header for c in ",;\t") else ","
    records = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))

    header_at = next((i for i, values in enumerate(records) if values), None)
    if header_at is None:
        return CsvTable([], [], warnings=warnings)
    fieldnames = records[header_at]
    rows = [
        (i + 1, dict(zip(fieldnames, values, strict=False)))
        for i, values in enumerate(records)
        if i > header_at and values
    ]
    return CsvTable(fieldnames, rows, header_at + 1, warnings)


def read_domain_list(data: bytes, source: str) -> tuple[list[DomainInput], list[InputWarning]]:
    """The domain list: a CSV with the header `domain,industry,note`, not a bare list.

    The same domain twice would mean two passes through someone else's site, so the first
    occurrence wins.
    """
    table = read_excel_csv(data, source)
    warnings = table.warnings
    if "domain" not in table.fieldnames:
        raise InputError(f"{source}, row {table.header_row}: the header has no `domain` column")

    domains: list[DomainInput] = []
    seen: set[str] = set()
    for row_no, row in table.rows:
        domain = (row.get("domain") or "").strip()
        if not domain or domain.startswith("#"):
            continue
        if domain.lower() in seen:
            warnings.append(InputWarning("domain is repeated in the list, skipping it", row_no, domain))
            continue
        seen.add(domain.lower())
        industry = (row.get("industry") or "").strip().lower() or "other"
        if industry not in INDUSTRIES:
            warnings.append(
                InputWarning(f"unknown industry {industry!r}, using `other`", row_no, domain)
            )
            industry = "other"
        domains.append(DomainInput(domain=domain, industry=industry, note=(row.get("note") or "").strip()))
    if not domains:
        raise InputError(f"{source}: no domain was read")
    return domains, warnings


# --------------------------------------------------------------------------- #
# Excluded domains: an administrator who writes "do not scan us" is respected from the next run
# --------------------------------------------------------------------------- #
def read_exclusions(data: bytes) -> list[str]:
    """One domain per line; empty lines and anything after `#` are skipped."""
    text = data.decode("utf-8-sig", errors="replace")
    lines = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return [line for line in lines if line]


def _host(domain: str) -> str:
    host = urlsplit(domain if "://" in domain else f"//{domain}").hostname or ""
    return host.rstrip(".").removeprefix("www.")


def is_excluded(domain: str, exclusions: Iterable[str]) -> bool:
    """The host equals the entry or is a subdomain of it: the entry `x.rs` excludes both
    `www.x.rs` and `blog.x.rs`.

    No "registered domain": without the Public Suffix List `firma.co.rs` would become `co.rs`,
    and one request would exclude every company under `.co.rs`. A leading `www.` is stripped
    from the entry as well, because an administrator who writes `www.firma.rs` is asking that
    the company not be scanned.
    """
    host = _host(domain)
    for entry in exclusions:
        excluded = _host(entry)
        if excluded and (host == excluded or host.endswith("." + excluded)):
            return True
    return False
