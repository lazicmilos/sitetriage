"""CSV izlaz (§10.1). Jedan red po nalazu, ne po domenu — da može da se filtrira."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path

from skener.messages import render
from skener.models import DomainReport

FINDINGS_HEADER = [
    "domain",
    "industry",
    "rank",
    "check_id",
    "level",
    "category",
    "severity",
    "weight",
    "message_client",
    "evidence_json",
    "evidence_url",
    "scanned_at",
]

SUMMARY_HEADER = [
    "domain",
    "industry",
    "rank",
    "status",
    "level2_ran",
    "total_score",
    "max_finding_weight",
    "findings_count",
    "unknowns_count",
    "top_check_id",
]


def write_findings(
    path: Path, reports: Sequence[DomainReport], *, bom: bool = False, lang: str = "sr"
) -> Path:
    rows = [
        [
            report.domain,
            report.industry,
            report.rank,
            finding.check_id,
            finding.level,
            finding.category,
            finding.severity,
            finding.weight,
            render(finding, lang).client,
            json.dumps(finding.evidence, ensure_ascii=False),
            finding.evidence_urls[0] if finding.evidence_urls else "",
            report.scanned_at,
        ]
        for report in reports
        for finding in report.findings
    ]
    return _write(path, FINDINGS_HEADER, rows, bom)


def write_summary(path: Path, reports: Sequence[DomainReport], *, bom: bool = False) -> Path:
    rows = [
        [
            report.domain,
            report.industry,
            report.rank,
            report.status,
            int(report.level2_ran),
            report.total_score,
            report.max_finding_weight,
            len(report.findings),
            len(report.unknowns),
            report.findings[0].check_id if report.findings else "",
        ]
        for report in reports
    ]
    return _write(path, SUMMARY_HEADER, rows, bom)


def _write(path: Path, header: Sequence[str], rows: Sequence[Sequence[object]], bom: bool) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # BOM samo kad se traži: Excel ga traži, svaki drugi alat ga smatra smećem.
    encoding = "utf-8-sig" if bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)  # RFC 4180
        writer.writerow(header)
        writer.writerows(rows)
    return path
