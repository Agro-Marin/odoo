#!/usr/bin/env python3
"""Gate a package README's module index against the package.

Several packages in the framework core document themselves with a per-module
table — `odoo/db/`, `odoo/http/` and `odoo/upgrade_code/` under "Module map",
`odoo/_monkeypatches/` under "Patch Index"; `PACKAGE_INDEXES` below is the
authoritative list.  They are the best documentation in the tree, and they were
the *least* protected: `subsystem_map_check.py` gates `module.md`'s
top-level map, `doc_link_gate.py` proves a referenced file exists, and neither
looks inside a package README.  A module added to `odoo/db/` appears in no
index until someone remembers, and `db/README.md` explicitly invites additions
("Add the check here when you add an invariant above") — an instruction with no
enforcement behind it.

The rule is symmetric:

1. **Every module named by the index must exist.**
2. **Every module in the package must be named by the index** — `__init__.py`
   excepted, which may be listed (``db/`` does) but is never required.

**The section scoping is the load-bearing part**, not an implementation detail.
These READMEs contain *other* tables that also name ``.py`` files, and some of
those files are deliberately gone: `_monkeypatches/README.md` has a **Recently
Removed** table listing `urllib3.py`, `lxml.py`, `xlrd.py`, `zeep.py`,
`pytz.py`, `xlwt.py` — every one correctly absent from the tree — and a
**Removal Criteria** table naming modules that still exist. A checker that
simply scanned the file for backticked module names would report six failures
against a document that is exactly right. So each index declares the heading
that introduces it, and only rows under that heading (up to the next heading of
the same or higher level) count as the inventory.

Usage::

    python tooling/architecture/package_index_check.py            # report
    python tooling/architecture/package_index_check.py --check    # CI: exit 1
    python tooling/architecture/package_index_check.py --json     # machine-readable
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

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="package_index_check")
CORE_ROOT = REPO_ROOT / "odoo"

PACKAGE_INDEXES: dict[str, tuple[str, str]] = {
    "db": ("README.md", "## Module map"),
    "_monkeypatches": ("README.md", "## Patch Index"),
    "http": ("README.md", "## Module map"),
    "upgrade_code": ("README.md", "## Module map"),
}

READMES_WITHOUT_AN_INDEX: frozenset[str] = frozenset()

OPTIONAL_MODULES = frozenset({"__init__"})

_ROW_RE = re.compile(r"^\|\s*`(?P<name>[^`/]+)\.py`")

_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s")


@dataclass
class PackageReport:
    package: str
    listed: set[str] = field(default_factory=set)
    actual: set[str] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)
    phantom: list[str] = field(default_factory=list)
    wrong_counts: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.phantom and not self.wrong_counts


@dataclass
class Report:
    packages: list[PackageReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.packages)


def extract_section(text: str, heading: str) -> list[str]:

    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == heading)
    except StopIteration:
        raise ValueError(f"heading {heading!r} not found") from None

    level = len(_HEADING_RE.match(heading).group("hashes"))
    section: list[str] = []
    for line in lines[start + 1 :]:
        match = _HEADING_RE.match(line)
        if match and len(match.group("hashes")) <= level:
            break
        section.append(line)
    return section


def listed_modules(section: list[str]) -> set[str]:
    return {match.group("name") for line in section if (match := _ROW_RE.match(line))}


def actual_modules(package_dir: Path) -> set[str]:
    if not package_dir.is_dir():
        return set()
    return {p.stem for p in package_dir.glob("*.py")}


SELF_COUNTS: dict[str, dict[str, str]] = {
    "_monkeypatches": {
        r"\*\*Total\*\*: (\d+) files": "files",
        r"\((\d+) patches": "patches",
    },
}


def _measure(kind: str, package_dir: Path) -> int:
    stems = {p.stem for p in package_dir.glob("*.py")} - OPTIONAL_MODULES
    if kind == "patches":
        return sum(not s.startswith("_") for s in stems)
    if kind == "files":
        return len(stems)
    raise ValueError(f"unknown count kind {kind!r}")


def check(core_root: Path | None = None, indexes: dict | None = None) -> Report:
    core_root = core_root or CORE_ROOT
    indexes = PACKAGE_INDEXES if indexes is None else indexes
    report = Report()

    for package, (readme_name, heading) in sorted(indexes.items()):
        package_dir = core_root / package
        readme = package_dir / readme_name
        if not readme.is_file():
            raise ValueError(f"{package}: {readme_name} not found at {readme}")

        section = extract_section(readme.read_text(encoding="utf-8"), heading)
        listed = listed_modules(section)
        actual = actual_modules(package_dir)

        pkg = PackageReport(package=package, listed=listed, actual=actual)
        pkg.missing = sorted(actual - listed - OPTIONAL_MODULES)
        pkg.phantom = sorted(listed - actual)

        whole = readme.read_text(encoding="utf-8")
        for pattern, kind in SELF_COUNTS.get(package, {}).items():
            match = re.search(pattern, whole)
            if match is None:
                raise ValueError(
                    f"{package}: SELF_COUNTS pattern {pattern!r} matched nothing "
                    f"in {readme_name}. Either the README stopped stating that "
                    f"count (drop the entry from SELF_COUNTS) or its wording "
                    f"changed (update the pattern). Skipping it silently would "
                    f"retire the check without anyone deciding to."
                )
            stated, measured = int(match.group(1)), _measure(kind, package_dir)
            if stated != measured:
                pkg.wrong_counts.append((kind, stated, measured))

        report.packages.append(pkg)

    return report


def render(report: Report) -> str:
    out: list[str] = []
    out.append("Package README index check")
    out.append("=" * 64)
    for pkg in report.packages:
        status = "  ok" if pkg.ok else "fail"
        out.append(
            f"[{status}] odoo/{pkg.package}/README.md — "
            f"{len(pkg.listed)} listed, {len(pkg.actual)} on disk"
        )
        out.extend(
            f"           + odoo/{pkg.package}/{name}.py is not in the index"
            for name in pkg.missing
        )
        out.extend(
            f"           - index names {name}.py, which does not exist"
            for name in pkg.phantom
        )
        out.extend(
            f"           ! README says {stated} {kind}, package has {measured}"
            for kind, stated, measured in pkg.wrong_counts
        )
    out.append("-" * 64)
    out.append("")
    if report.ok:
        out.append("Every package index matches its package. ✓")
    else:
        out.append(
            "A package README has drifted from the package it documents.\n"
            "Update the table or the self-stated counts (or the tree), "
            "then re-run."
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when an index has drifted"
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
                    "packages": [
                        {
                            "package": p.package,
                            "listed": sorted(p.listed),
                            "missing": p.missing,
                            "phantom": p.phantom,
                        }
                        for p in report.packages
                    ],
                },
                indent=2,
            )
        )
    else:
        print(render(report))

    return 1 if (args.check and not report.ok) else 0


if __name__ == "__main__":
    sys.exit(main())
