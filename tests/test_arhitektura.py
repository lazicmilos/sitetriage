"""Ko sme šta da uvozi. Pravila se čitaju iz izvornog koda, bez izvršavanja."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SKENER = Path(__file__).parent.parent / "skener"


def uvozi(path: Path) -> set[str]:
    """Sve što fajl uvozi, i na vrhu i unutar funkcije: `from a.b import c` daje `a.b.c`."""
    imena: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imena.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imena.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imena


def pod(ime: str, modul: str) -> bool:
    return ime == modul or ime.startswith(modul + ".")


def test_cli_ne_orkestrira_sam():
    """Redosled faza živi samo u `skener.pipeline`; inače bi ga web worker kopirao."""
    zabranjeno = ("skener.fetch.http", "skener.fetch.browser", "skener.score")
    losi = {ime for ime in uvozi(SKENER / "cli.py") if any(pod(ime, m) for m in zabranjeno)}
    assert not losi, f"cli.py uvozi {sorted(losi)}; to pripada pipeline-u"


@pytest.mark.parametrize("path", sorted((SKENER / "checks").glob("*.py")), ids=lambda p: p.name)
def test_provere_ne_diraju_mrezu(path):
    """Provera dobija snapshot i vraća nalaze. Ako joj treba nešto sa mreže, snapshotu fali polje."""
    zabranjeno = (
        "httpx", "playwright", "skener.fetch", "skener.pipeline", "skener.messages", "skener.report"
    )
    losi = {
        ime
        for ime in uvozi(path)
        if any(pod(ime, m) for m in zabranjeno) and not pod(ime, "skener.fetch.urls")
    }
    assert not losi, f"{path.name} uvozi {sorted(losi)}"
