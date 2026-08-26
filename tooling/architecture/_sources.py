from __future__ import annotations

import itertools
from pathlib import Path

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules"}
)

POLYGLOT_MARKER = "''':'"

POLYGLOT_PROLOGUE_LINES = 10


def is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def display_across_repos(path: Path, root: Path) -> str:
    for base in (root.parent, root):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def is_polyglot(path: Path) -> bool:
    if path.suffix or not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            head = list(itertools.islice(handle, POLYGLOT_PROLOGUE_LINES))
    except OSError:
        return False
    return any(line.startswith(POLYGLOT_MARKER) for line in head)


def iter_python_files(
    root: Path,
    *,
    include_tests: bool = False,
    include_polyglots: bool = True,
) -> list[Path]:
    if not root.is_dir():
        return []
    found = [
        path
        for path in root.rglob("*.py")
        if not SKIP_DIRS & set(path.parts)
        and (include_tests or not is_test_path(path))
    ]
    if include_polyglots:
        found.extend(
            path
            for path in root.rglob("*")
            if not SKIP_DIRS & set(path.parts)
            and (include_tests or not is_test_path(path))
            and is_polyglot(path)
        )
    return sorted(found)
