#!/usr/bin/env python3
"""Gate the *descriptive* half of the architecture docs against the tree.

``layer_check.py`` enforces the architecture's **contracts** (who may import
whom).  Nothing enforced its **map** — the "Subsystem map" tree that tells a
reader which packages exist and what lives in them.  ``doc_link_gate.py`` proves
a referenced ``.md`` file *exists*; it says nothing about whether a described
package still matches its directory.  So the map is the one part of the
architecture documentation that can rot silently, and it did: it depicted
``db/connectivity``, ``db/resilience``, ``http/core`` and ``http/features`` as
subdirectories, none of which exist, and the invented ``core`` node masked the
real, undocumented ``http/core.py``.

This checker closes that loop.  It parses the map and enforces two rules:

**1. No fictional paths.**  Every path-shaped name in the map must exist in the
tree.  A logical grouping that is not a directory must say so by writing itself
``[in brackets]``; the checker then treats it as a label rather than a path, and
attributes the names after it to the enclosing package.

**2. An enumeration that starts must finish.**  The map does not have to list a
package's contents — ``libs/`` (138 files) is deliberately summarised in one
line.  But a package whose children the map *does* enumerate must be enumerated
*exhaustively*, per kind: name one module and every module must be named; name
one subpackage and every subpackage must be named.  Naming only ``assets/``
under ``tools/`` is what let ``babel_extractors/`` and ``pdf/`` go unmentioned.

Splitting the rule by kind is what keeps it proportionate.  ``tools/`` lists
subpackages only, so the gate demands its three subpackages and not its 35
modules; ``db/`` lists modules only, so it demands all 17 and does not care that
it has no subpackages.  A blanket "list everything" rule would force 138 lines
of ``libs/`` into a map whose value is that it fits on a screen.

Exempt everywhere: ``__init__.py`` (the package itself), ``__pycache__``,
``tests/`` (test suites are documented by ``doc/coding_guidelines.rst`` §6, not
by the subsystem map), and non-Python files.

Usage::

    python tooling/architecture/subsystem_map_check.py            # report
    python tooling/architecture/subsystem_map_check.py --check    # CI: exit 1
    python tooling/architecture/subsystem_map_check.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0030"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="subsystem_map_check")

ARCHITECTURE_MD = REPO_ROOT / "doc" / "architecture" / "module.md"
CORE_ROOT = REPO_ROOT / "odoo"

MAP_HEADING = "## Subsystem map"

EXEMPT_DIRS = frozenset({"__pycache__", "tests"})

EXEMPT_MODULES = frozenset({"__init__", "__main__"})

_GLYPHS = "│├└─"

_GROUP_RE = re.compile(r"^\[(?P<label>[^\]]+)\]\s*")

_INDENT = 4


def _split_top_level(text: str) -> list[str]:

    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and char in ",·":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


_NAME_RE = re.compile(r"^(?P<name>[A-Za-z0-9_][A-Za-z0-9_.\-]*)(?P<slash>/?)\s*")


def _is_gloss(remainder: str) -> bool:

    rest = remainder.strip()
    while rest.startswith("("):
        depth = 0
        for index, char in enumerate(rest):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    rest = rest[index + 1 :].strip()
                    break
        else:
            return False
    return not rest


def parse_names(content: str) -> tuple[list[tuple[str, bool]], bool]:

    names: list[tuple[str, bool]] = []
    for part in _split_top_level(content):
        match = _NAME_RE.match(part)
        if not match:
            return names, False
        remainder = part[match.end() :]
        name = match.group("name")
        is_dir = bool(match.group("slash"))
        if _is_gloss(remainder):
            names.append((name, is_dir))
            continue
        names.append((name, is_dir))
        return names, False
    return names, True


@dataclass
class MapEntry:
    name: str
    is_dir: bool
    parent: str
    line: int


@dataclass
class Report:
    entries: list[MapEntry] = field(default_factory=list)
    fictional: list[tuple[str, int]] = field(default_factory=list)
    undocumented: list[tuple[str, str]] = field(default_factory=list)
    enumerated: dict[str, set[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.fictional and not self.undocumented


def extract_map_block(
    text: str, source: Path | str = ARCHITECTURE_MD
) -> tuple[list[str], int]:

    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == MAP_HEADING)
    except StopIteration:
        raise ValueError(f"{source}: no {MAP_HEADING!r} heading") from None

    fence = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("```")), None
    )
    if fence is None:
        raise ValueError(f"{source}: {MAP_HEADING!r} has no fenced block")
    end = next(
        (i for i in range(fence + 1, len(lines)) if lines[i].startswith("```")), None
    )
    if end is None:
        raise ValueError(f"{source}: unterminated fence after {MAP_HEADING!r}")
    return lines[fence + 1 : end], fence + 2


def parse_map(block: list[str], first_line: int) -> list[MapEntry]:

    entries: list[MapEntry] = []
    stack: dict[int, str] = {0: ""}
    last_parent = ""
    continues_names = False

    for offset, raw in enumerate(block):
        if not raw.strip():
            continue
        stripped = raw.rstrip()
        content = stripped.lstrip(_GLYPHS + " ")
        if not content or content == "odoo/":
            continue

        lineno = first_line + offset
        indent = len(stripped) - len(content)
        depth = max(1, round(indent / _INDENT))
        has_connector = "├" in stripped or "└" in stripped

        if has_connector:
            parent = stack.get(depth - 1, "")
            last_parent = parent
        elif continues_names:
            parent = last_parent
        else:
            continue

        group = _GROUP_RE.match(content)
        if group:
            content = content[group.end() :]

        names, complete = parse_names(content)
        continues_names = complete

        for name, is_dir in names:
            entries.append(
                MapEntry(name=name, is_dir=is_dir, parent=parent, line=lineno)
            )
            if is_dir:
                child_path = f"{parent}/{name}" if parent else name
                stack[depth] = child_path

    return entries


def _actual_children(package: str, core_root: Path) -> tuple[set[str], set[str]]:
    root = core_root / package if package else core_root
    if not root.is_dir():
        return set(), set()
    modules = {
        p.stem
        for p in root.iterdir()
        if p.is_file() and p.suffix == ".py" and p.stem not in EXEMPT_MODULES
    }
    packages = {
        p.name
        for p in root.iterdir()
        if p.is_dir() and p.name not in EXEMPT_DIRS and (p / "__init__.py").exists()
    }
    return modules, packages


def check(md_path: Path | None = None, core_root: Path | None = None) -> Report:

    md_path = md_path or ARCHITECTURE_MD
    core_root = core_root or CORE_ROOT
    block, first_line = extract_map_block(md_path.read_text(encoding="utf-8"), md_path)
    entries = parse_map(block, first_line)
    report = Report(entries=entries)

    for entry in entries:
        rel = f"{entry.parent}/{entry.name}" if entry.parent else entry.name
        target = core_root / rel
        exists = (
            target.is_dir() if entry.is_dir else target.with_suffix(".py").is_file()
        )
        if not exists:
            kind = "directory" if entry.is_dir else "module"
            suffix = "/" if entry.is_dir else ".py"
            label = f"odoo/{rel}{suffix}  ({kind} named by the map, not in the tree)"
            report.fictional.append((label, entry.line))

    by_parent: dict[str, list[MapEntry]] = {}
    for entry in entries:
        by_parent.setdefault(entry.parent, []).append(entry)

    for package, children in by_parent.items():
        named_modules = {c.name for c in children if not c.is_dir}
        named_packages = {c.name for c in children if c.is_dir}
        actual_modules, actual_packages = _actual_children(package, core_root)
        report.enumerated[package] = named_modules | named_packages

        if named_modules:
            for missing in sorted(actual_modules - named_modules):
                report.undocumented.append((package, f"{missing}.py"))
        if named_packages:
            for missing in sorted(actual_packages - named_packages):
                report.undocumented.append((package, f"{missing}/"))

    return report


def render(report: Report) -> str:
    out: list[str] = []
    out.append("Subsystem-map coherence check")
    out.append("=" * 64)
    out.append(f"doc/architecture/module.md  ->  {CORE_ROOT}")
    out.append("")
    out.append(f"Names parsed from the map: {len(report.entries)}")
    out.append(f"Packages the map enumerates: {len(report.enumerated)}")
    out.append("")

    if report.fictional:
        out.append(f"[fail] {len(report.fictional)} path(s) in the map do not exist:")
        for name, line in report.fictional:
            out.append(f"    module.md:{line}  {name}")
        out.append("")
    else:
        out.append("[  ok] every path named by the map exists")

    if report.undocumented:
        out.append(
            f"[fail] {len(report.undocumented)} item(s) missing from an "
            "enumerated package:"
        )
        for package, item in report.undocumented:
            prefix = f"odoo/{package}/" if package else "odoo/"
            out.append(f"    {prefix}{item}")
        out.append("")
    else:
        out.append("[  ok] every enumerated package is enumerated exhaustively")

    out.append("-" * 64)
    out.append("")
    if report.ok:
        out.append("Subsystem map matches the tree. ✓")
    else:
        out.append(
            "The subsystem map has drifted from the tree. Update the map in\n"
            "doc/architecture/module.md (or the tree), then re-run. A\n"
            "logical grouping that is not a directory must be written "
            "[in brackets]."
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when the map has drifted"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        report = check()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "fictional": [
                        {"name": n, "line": ln} for n, ln in report.fictional
                    ],
                    "undocumented": [
                        {"package": p, "item": i} for p, i in report.undocumented
                    ],
                    "enumerated": {k: sorted(v) for k, v in report.enumerated.items()},
                },
                indent=2,
            )
        )
    else:
        print(render(report))

    return 1 if (args.check and not report.ok) else 0


if __name__ == "__main__":
    sys.exit(main())
