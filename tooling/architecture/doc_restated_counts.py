from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _repo_root import find_odoo_root

ADR = "0041"

ROOT = find_odoo_root(Path(__file__).resolve())


class Figure(NamedTuple):
    name: str
    path: Path
    pattern: re.Pattern[str]
    measure: Callable[[], tuple[int, ...]]
    render: Callable[[tuple[int, ...]], tuple[str, ...]]
    tolerance: float = 0.0


def _plain(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(str(v) for v in values)


def _grouped(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{v:,}" for v in values)


def _padded(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{v:04d}" for v in values)


def _rounded(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(str(round(v / 10) * 10) for v in values)


def _within(stated: str, measured: int, tolerance: float) -> bool:
    return abs(int(stated.replace(",", "")) - measured) <= max(
        2, round(measured * tolerance)
    )


def bundled_modules() -> tuple[int, ...]:
    return (
        sum(
            1
            for path in (ROOT / "addons").iterdir()
            if (path / "__manifest__.py").is_file()
        ),
    )


def _suite_methods(module: str) -> int:
    for tree in ("addons", "odoo/addons"):
        base = ROOT / tree / module / "tests"
        if base.is_dir():
            break
    else:
        raise FileNotFoundError(f"{module}/tests not found in either addon tree")
    return sum(
        sum(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test")
            for node in ast.walk(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            )
        )
        for path in sorted(base.rglob("*.py"))
    )


def metadata_call_sites() -> tuple[int, ...]:
    counts = []
    for attr in ("_name", "_fields"):
        pattern = re.compile(rf"self\.{attr}\b")
        counts.append(
            sum(
                len(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
                for tree in ("odoo/addons", "addons")
                for path in (ROOT / tree).rglob("*.py")
            )
        )
    return tuple(counts)


def adr_range() -> tuple[int, ...]:
    numbers = sorted(
        int(path.name[:4])
        for path in (ROOT / "doc" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")
    )
    return (numbers[0], numbers[-1])


ARCHITECTURE = ROOT / "doc" / "architecture" / "ARCHITECTURE.md"
GATES = ROOT / "doc" / "architecture" / "gates.md"
METADATA = ROOT / "odoo" / "orm" / "models" / "mixins" / "_metadata.py"

FIGURES: tuple[Figure, ...] = (
    Figure(
        "bundled_modules",
        GATES,
        re.compile(r"the\s+(\d[\d,]*)\s+bundled\s+modules"),
        bundled_modules,
        _plain,
    ),
    Figure(
        "test_orm_methods",
        GATES,
        re.compile(r"\*\*([\d,]+)\s+test\s+methods\*\*"),
        lambda: (_suite_methods("test_orm"),),
        _grouped,
    ),
    Figure(
        "test_read_group_methods",
        GATES,
        re.compile(r"`test_read_group`\s+\((\d[\d,]*)\s+test"),
        lambda: (_suite_methods("test_read_group"),),
        _plain,
    ),
    Figure(
        "test_access_rights_methods",
        GATES,
        re.compile(r"`test_access_rights`\s+\((\d[\d,]*),"),
        lambda: (_suite_methods("test_access_rights"),),
        _plain,
    ),
    Figure(
        "metadata_call_sites",
        METADATA,
        re.compile(
            r"``self\._name``\s+has\s+about\s+(\d[\d,]*)\s+sites\s+and\s+"
            r"``self\._fields``\s+about\s+(\d[\d,]*)"
        ),
        metadata_call_sites,
        _rounded,
        tolerance=0.05,
    ),
    Figure(
        "adr_range",
        ARCHITECTURE,
        re.compile(r"architecture\s+decisions,\s+(\d{4})–(\d{4})"),
        adr_range,
        _padded,
    ),
)


def _match(figure: Figure) -> re.Match[str]:
    match = figure.pattern.search(figure.path.read_text(encoding="utf-8"))
    if match is None:
        raise LookupError(
            f"{figure.name}: no sentence in {figure.path.name} matches "
            f"{figure.pattern.pattern!r}. The figure is no longer checked; "
            f"restore the sentence or drop the figure from FIGURES."
        )
    return match


def check() -> list[str]:
    problems = []
    for figure in FIGURES:
        stated = _match(figure).groups()
        measured = figure.measure()
        if figure.tolerance:
            fresh = all(
                _within(s, m, figure.tolerance)
                for s, m in zip(stated, measured, strict=True)
            )
        else:
            fresh = tuple(stated) == figure.render(measured)
        if not fresh:
            problems.append(
                f"{figure.name} in {figure.path.name}: states "
                f"{', '.join(stated)}, measured "
                f"{', '.join(str(m) for m in measured)}"
            )
    return problems


def update() -> list[str]:
    changed = []
    for figure in FIGURES:
        raw = figure.path.read_text(encoding="utf-8")
        match = _match(figure)
        measured = figure.measure()
        if figure.tolerance and all(
            _within(s, m, figure.tolerance)
            for s, m in zip(match.groups(), measured, strict=True)
        ):
            continue
        expected = figure.render(measured)
        text = raw
        for index, value in reversed(list(enumerate(expected, start=1))):
            start, end = match.span(index)
            text = text[:start] + value + text[end:]
        if text != raw:
            figure.path.write_text(text, encoding="utf-8")
            changed.append(f"{figure.name}: {', '.join(expected)}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    if args.update:
        changed = update()
        print("\n".join(changed) if changed else "already fresh")
        return 0
    problems = check()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
