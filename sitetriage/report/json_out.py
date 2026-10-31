"""JSON report: the contract for programs that read the output (web app, `diff`, `outcomes`, CRM).

A serialized `ScanResult`, without sentences: a sentence is built from the evidence in the
reader's language. `sitetriage/schema/report-3.json` describes the shape, and the rules for
changing it are in ADR-011.
"""

from __future__ import annotations

import json
from pathlib import Path

from sitetriage.models import ScanResult, to_jsonable


def write(path: Path, result: ScanResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
