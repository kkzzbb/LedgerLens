"""DemoBank imports nothing from `ledgerlens` (`architecture.md` §3).

Every `.py` file under `demobank/` (except `.venv/`) is parsed with `ast`. An
absolute import whose top-level module is `ledgerlens` fails the test.
Relative imports and modules that only contain the word are allowed.
"""

import ast
from pathlib import Path

import pytest

DEMOBANK_DIR = Path(__file__).resolve().parents[2]
FORBIDDEN = "ledgerlens"


def forbidden_imports(source: str, forbidden: str = FORBIDDEN) -> list[str]:
    """The absolute imports in `source` whose top-level module is `forbidden`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if alias.name.split(".")[0] == forbidden
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module is not None
            and node.module.split(".")[0] == forbidden
        ):
            found.append(node.module)
    return found


def python_files(root: Path) -> list[Path]:
    """Every `.py` file under `root`, outside `.venv/`."""
    return sorted(
        path for path in root.rglob("*.py") if ".venv" not in path.relative_to(root).parts
    )


@pytest.mark.parametrize(
    "source",
    [
        "import ledgerlens",
        "import ledgerlens.config as c",
        "from ledgerlens.x import y",
        "import os, ledgerlens.db",
        "from ledgerlens import config",
        "def f() -> None:\n    import ledgerlens\n",
    ],
)
def test_import_of_ledgerlens_is_flagged(source: str) -> None:
    assert forbidden_imports(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import ledgerlens_tools",
        "from .ledgerlens import y",
        "from . import ledgerlens",
        "x = 'ledgerlens'",
        "from demobank.ledgerlens import y",
        "import os",
    ],
)
def test_other_imports_are_not_flagged(source: str) -> None:
    assert forbidden_imports(source) == []


def test_the_walk_finds_the_package_and_skips_the_virtualenv() -> None:
    files = python_files(DEMOBANK_DIR)

    assert DEMOBANK_DIR / "demobank" / "app.py" in files
    assert Path(__file__).resolve() in files
    assert not any(".venv" in path.parts for path in files)


def test_demobank_imports_nothing_from_ledgerlens() -> None:
    offenders = {
        str(path.relative_to(DEMOBANK_DIR)): found
        for path in python_files(DEMOBANK_DIR)
        if (found := forbidden_imports(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}
