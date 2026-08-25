"""What counts as a Python source, and how to name one, in one place.

Six gates carried `_is_test_path` byte-identically and seven carried `_display`.
That much is plain duplication. The reason this module exists rather than a
shared constant is the third function.

EVERY GATE HERE WALKS FOR `*.py`, AND THAT MISSES REAL PYTHON. Five files in
`tooling/` are extension-less `#!/bin/sh` polyglots -- `hoot`, `hoot-shard`,
`hoot-affected`, `bench/render_bench`, `bench/discuss_bench` -- totalling 1,647
lines. `ruff.toml` already had to name them one by one in `extend-include`, and
its comment records what the omission cost: they are "23% of tooling's Python"
that `ruff check tooling/` reported "All checks passed!" over, and the two bench
runners "were carrying 11 real findings that `ruff check tooling/` had never once
reported".

That is not a ruff problem, it is a glob problem, and every gate that globs
`*.py` has it. Measured on `py_function_length`: `tooling/` scores 15 offenders
and 657 excess lines over its `*.py`, and 20 offenders and 910 excess lines once
the polyglots are included -- `hoot:main` alone is 222 lines.

:func:`iter_python_files` finds both. The polyglots are DISCOVERED by their
marker rather than listed, because a list is a second copy of the tree: the same
`grep -rl "^''':'"` that `ruff.toml`'s comment names as the way to enumerate
them.
"""

from __future__ import annotations

import itertools
from pathlib import Path

#: Directories no gate wants to walk into, whatever it is measuring.
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules"}
)

#: The line the `#!/bin/sh` polyglot prologue turns on: a shell no-op that
#: opens a Python string literal, so the shell and the interpreter read the
#: same file differently. Matching the MARKER rather than keeping a list means
#: a sixth one is found the day it lands, and it is the same probe
#: `ruff.toml`'s comment names for enumerating them.
POLYGLOT_MARKER = "''':'"

#: How far in to look for it. It sits on line 4 of every current runner --
#: under the shebang, a `ruff format` directive and a `# fmt: off` -- and two
#: lines was the first guess here, which found none of the five.
POLYGLOT_PROLOGUE_LINES = 10


def is_test_path(path: Path) -> bool:
    """Whether *path* is test code, by the rule six gates already agreed on."""
    return "tests" in path.parts or path.name.startswith("test_")


def display(path: Path, root: Path) -> str:
    """*path* relative to *root*, or absolute when it lies outside.

    The absolute fallback is deliberate and is why this is not a bare
    `relative_to`: `py_unresolved_calls` and the per-addon gates measure sibling
    checkouts, which are not under the odoo root at all, and a raising
    `relative_to` would turn a finding in `agromarin/` into a crash.
    """
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def display_across_repos(path: Path, root: Path) -> str:
    """*path* relative to the WORKSPACE, so a sibling checkout names itself.

    `display` answers "where in this repo?" and falls back to an absolute path
    outside it. A cross-repo gate wants the other answer: a finding in the
    sibling should read `agromarin/models/thing.js`, not
    `/home/…/Odoo/agromarin/models/thing.js`, because the repo name is the part
    the reader needs and the absolute prefix is noise that differs per machine.
    """
    for base in (root.parent, root):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def is_polyglot(path: Path) -> bool:
    """Whether an extension-less file is one of the `#!/bin/sh` Python runners.

    Read rather than guessed: the shebang is `/bin/sh`, so nothing about the
    first line says Python, and the marker further down the prologue is what
    distinguishes one of these from an ordinary shell script.
    """
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
    """Every Python source under *root*, sorted, `*.py` and polyglot alike.

    `include_tests` defaults to False because that is what the counting gates
    want; the two that deliberately measure test code pass True and say why at
    the call site, which is one place more than the divergence used to be
    recorded in.
    """
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
