"""Mutation testing (docs/sr/plan-testiranja.md).

mutmut runs only on Linux, so it is started through Docker:

    docker compose run --rm sitetriage python scripts/mutation.py

The code in the image is read-only, so mutmut works on a copy in /tmp. Which modules are
mutated and which tests catch them is set in pyproject.toml, [tool.mutmut].

The `check(...)` decorator in the registry runs at import time, before mutmut switches the
mutant on, so mutmut reports its mutants as survivors even though the tests catch them.
They are checked by hand, see docs/sr/izvestaj-testiranja-2.md.

mutmut 3.2.3 does not create mutants in decorated functions, so it does not mutate the bodies
of checks (`@check`); the score applies to the helper functions. See the mutation testing
section of docs/sr/izvestaj-testiranja-3.md.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

MUTMUT = "mutmut==3.2.3"
# mutmut 3.2.3 pins junit-xml==1.8, which exists only as a source package and does not build
# with recent setuptools. 1.9 has the same API and ships a wheel, so the dependencies are
# installed first and mutmut itself without its pins.
MUTMUT_DEPS = ["junit-xml==1.9", "parso", "click", "setproctitle", "textual"]
ROOT = Path(__file__).resolve().parent.parent
COPY = Path("/tmp/mutation")


def main() -> int:
    pip = [sys.executable, "-m", "pip", "install", "-q", "--user"]
    subprocess.run([*pip, *MUTMUT_DEPS], check=True)
    subprocess.run([*pip, "--no-deps", MUTMUT], check=True)
    shutil.rmtree(COPY, ignore_errors=True)
    shutil.copytree(ROOT, COPY, ignore=shutil.ignore_patterns(".git", "mutants", "work", "out"))
    mutmut = str(Path.home() / ".local" / "bin" / "mutmut")
    subprocess.run([mutmut, "run", "--max-children", "4"], cwd=COPY)
    return subprocess.run([mutmut, "results"], cwd=COPY).returncode


if __name__ == "__main__":
    sys.exit(main())
