from __future__ import annotations

import itertools
from collections.abc import Iterator
from pathlib import Path

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".worktrees", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules"}
)

POLYGLOT_MARKER = "''':'"

POLYGLOT_PROLOGUE_LINES = 10


def _raise_walk_error(error: OSError) -> None:
    raise error


def walk_sources(root: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
    """Walk one source scope, pruning caches and nested Git checkouts.

    The selected root may itself be a worktree. Boundaries apply beneath it;
    a nested .git file (worktree) or directory (clone) starts another scope.
    """
    if not root.is_dir():
        return
    for directory, dirs, files in root.walk(on_error=_raise_walk_error):
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in SKIP_DIRS and not (directory / name / ".git").exists()
        )
        yield directory, dirs, files


def iter_files(root: Path, pattern: str = "*") -> Iterator[Path]:
    for directory, _dirs, files in walk_sources(root):
        for name in sorted(files):
            path = directory / name
            if path.match(pattern) and path.is_file():
                yield path


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
        for path in iter_files(root, "*.py")
        if include_tests or not is_test_path(path)
    ]
    if include_polyglots:
        found.extend(
            path
            for path in iter_files(root)
            if (include_tests or not is_test_path(path)) and is_polyglot(path)
        )
    return sorted(found)
