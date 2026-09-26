"""JSON izveštaj: ugovor za web aplikaciju, `diff`, `outcomes` i kupca koda.

Serijalizovan `ScanResult`, bez rečenica: rečenica se pravi iz dokaza na jeziku onoga ko
čita. Oblik opisuje `skener/schema/report-2.json`, a pravila promene su u README-u.
"""

from __future__ import annotations

import json
from pathlib import Path

from skener.models import ScanResult, to_jsonable


def write(path: Path, result: ScanResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
