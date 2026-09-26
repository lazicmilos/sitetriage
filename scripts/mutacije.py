"""Mutaciono testiranje (docs/plan-testiranja.md).

mutmut radi samo na Linux-u, pa se pokreće kroz Docker:

    docker compose run --rm skener python scripts/mutacije.py

Kod u slici je samo za čitanje, pa mutmut radi nad kopijom u /tmp. Koji moduli se
kvare i koji testovi ih hvataju piše u pyproject.toml, [tool.mutmut].

Dekorator `check(...)` u registru radi pri importu, pre nego što mutmut uključi
mutanta, pa njegove mutante mutmut prijavljuje kao preživele iako ih testovi hvataju.
Proverava se ručno — docs/izvestaj-testiranja-2.md.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

MUTMUT = "mutmut==3.2.3"
KOREN = Path(__file__).resolve().parent.parent
KOPIJA = Path("/tmp/mutacije")


def main() -> int:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--user", MUTMUT], check=True)
    shutil.rmtree(KOPIJA, ignore_errors=True)
    shutil.copytree(KOREN, KOPIJA, ignore=shutil.ignore_patterns(".git", "mutants", "rad", "out"))
    mutmut = str(Path.home() / ".local" / "bin" / "mutmut")
    subprocess.run([mutmut, "run", "--max-children", "4"], cwd=KOPIJA)
    return subprocess.run([mutmut, "results"], cwd=KOPIJA).returncode


if __name__ == "__main__":
    sys.exit(main())
