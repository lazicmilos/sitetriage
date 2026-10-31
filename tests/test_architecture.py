"""Who may import what. The rules are read from the source code, without running it."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "sitetriage"


def imports(path: Path) -> set[str]:
    """Everything a file imports, at the top and inside functions: `from a.b import c` gives `a.b.c`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def under(name: str, module: str) -> bool:
    return name == module or name.startswith(module + ".")


def test_cli_does_not_orchestrate_itself():
    """The order of the phases lives only in `sitetriage.pipeline`; otherwise a web worker would copy it."""
    forbidden = ("sitetriage.fetch.http", "sitetriage.fetch.browser", "sitetriage.score")
    bad = {name for name in imports(PACKAGE / "cli.py") if any(under(name, m) for m in forbidden)}
    assert not bad, f"cli.py imports {sorted(bad)}; that belongs to the pipeline"


@pytest.mark.parametrize("path", sorted((PACKAGE / "checks").glob("*.py")), ids=lambda p: p.name)
def test_checks_do_not_touch_the_network(path):
    """A check gets a snapshot and returns findings.

    If it needs something from the network, the snapshot is missing a field.
    """
    forbidden = (
        "httpx", "playwright", "sitetriage.fetch", "sitetriage.pipeline", "sitetriage.messages",
        "sitetriage.report",
    )
    bad = {
        name
        for name in imports(path)
        if any(under(name, m) for m in forbidden) and not under(name, "sitetriage.fetch.urls")
    }
    assert not bad, f"{path.name} imports {sorted(bad)}"
