"""Every ``import { x }`` finds an ``x`` in the module it names (ADR-0031).

A named import that resolves to nothing is not a runtime error you find in the
failing feature. The bundle is one concatenated program, so an unsatisfied
binding is a **link-time SyntaxError that kills the whole asset bundle** -- every
module in it, not the one with the typo. That is why this runs over the tree
rather than waiting for a page to load it.

IT IS THE CHEAPEST GATE HERE AND IT CATCHES REAL THINGS. Measured 2026-08-25, one
finding on a clean checkout::

    addons/stock/static/tests/generate_serial.test.js:
      imports 'parseNumberInput' from '@stock/widgets/generate_serial'
      which does not export it

The module had been reverted a revision while its template and its test stayed on
the newer one, and the consequence was larger than a red gate: the whole test
file could not link, so all six of its tests had been silently not running.

CROSS-REPO, AND IT HAS TO BE. A sibling checkout imports `@web` and `@mail`
specifiers it does not contain, so a repo-alone run cannot resolve them. The gate
yields **no verdict** for a specifier whose provider tree is absent rather than
guessing one -- an absent module is not a missing export -- which is why
`enterprise/` and `agromarin/` each re-run it from their own lane with this
checkout beside them, and why `design-themes` gained a lane in 2026-08-25 that
does the same.

Re-export forms are followed: `export { x } from …`, `export * from …`, and
declaration exports. A star re-export is why the resolver is a graph walk and not
a per-file lookup.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from cross_repo_coherence import SIBLING_REPOS_ROOT, default_consumer_repos
from js_imports import strip_comments

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0072"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="named_export_coherence")

NAMED_IMPORT_RE = re.compile(
    r"""import\s*(?:[A-Za-z_$][\w$]*\s*,\s*)?\{([^}]*)\}\s*from\s*["']([^"']+)["']"""
)
NAMED_EXPORT_RE = re.compile(r"""export\s*\{([^}]*)\}""")
DECL_EXPORT_RE = re.compile(
    r"""^[ \t]*export\s+(?:async\s+)?"""
    r"""(?:function\s*\*\s*|function\s+|class\s+|const\s+|let\s+|var\s+)"""
    r"""([A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)
DESTRUCTURED_EXPORT_RE = re.compile(
    r"""^[ \t]*export\s+(?:const|let|var)\s*([{\[][\s\S]*?[}\]])\s*=""", re.MULTILINE
)
STAR_REEXPORT_RE = re.compile(r"""export\s*\*\s*from\s*["']([^"']+)["']""")
MODULE_SPEC_RE = re.compile(r"^@([a-z0-9_]+)/(.+)$")
BINDING_RE = re.compile(r"""([A-Za-z_$][\w$]*)\s*(?::\s*([A-Za-z_$][\w$]*))?""")

NON_ADDON_SCOPES = {"odoo", "web_tour_tests"}


@dataclass(frozen=True)
class Unsatisfied:
    consumer: str
    specifier: str
    name: str
    target: str

    def __str__(self) -> str:
        return (
            f"{self.consumer}: imports '{self.name}' from '{self.specifier}' "
            f"which does not export it"
        )


def destructured_names(pattern: str) -> set[str]:

    names: set[str] = set()
    depth = 0
    current: list[str] = []
    parts: list[str] = []
    for ch in pattern.strip()[1:-1]:
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    for part in parts:
        part = part.split("=")[0].strip().lstrip(".")
        if not part:
            continue
        if match := BINDING_RE.match(part):
            names.add(match.group(2) or match.group(1))
    return names


def imported_names(brace_body: str) -> list[str]:
    names = []
    for part in brace_body.split(","):
        part = part.strip()
        if part:
            names.append(part.split(" as ")[0].strip())
    return [n for n in names if n and n != "default"]


IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def exported_names(brace_body: str) -> set[str]:

    names = set()
    for part in brace_body.split(","):
        part = part.strip()
        if part:
            name = part.split(" as ")[-1].strip()
            if IDENTIFIER_RE.match(name):
                names.add(name)
    return names


class Resolver:
    def __init__(self, addons_roots: list[Path]) -> None:
        self.addon_dirs: dict[str, Path] = {}
        for root in addons_roots:
            if not root.is_dir():
                continue
            for module_dir in sorted(root.iterdir()):
                static_src = module_dir / "static" / "src"
                if static_src.is_dir():
                    self.addon_dirs.setdefault(module_dir.name, static_src)
        self._cache: dict[Path, tuple[set[str], bool]] = {}

    def resolve(self, spec: str, importer: Path | None = None) -> Path | None:

        if spec.startswith("."):
            if importer is None:
                return None
            base = (importer.parent / spec).resolve()
        else:
            match = MODULE_SPEC_RE.match(spec)
            if not match:
                return None
            addon, subpath = match.groups()
            if addon in NON_ADDON_SCOPES or subpath.startswith(".."):
                return None
            static_src = self.addon_dirs.get(addon)
            if static_src is None:
                return None
            base = static_src / subpath
        for candidate in (base, base / "index.js", base.parent / f"{base.name}.js"):
            if candidate.is_file():
                return candidate
        return None

    def exports_of(
        self, path: Path, stack: frozenset[Path] = frozenset()
    ) -> tuple[set[str], bool]:

        if path in self._cache:
            return self._cache[path]
        if path in stack:
            return set(), False
        try:
            source = strip_comments(path.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError:  # pragma: no cover
            return set(), False
        names = set(DECL_EXPORT_RE.findall(source))
        for pattern in DESTRUCTURED_EXPORT_RE.findall(source):
            names |= destructured_names(pattern)
        for brace_body in NAMED_EXPORT_RE.findall(source):
            names |= exported_names(brace_body)
        complete = True
        hit_cycle = False
        for star_spec in STAR_REEXPORT_RE.findall(source):
            target = self.resolve(star_spec, path)
            if target is None:
                complete = False
                continue
            sub_names, sub_complete = self.exports_of(target, stack | {path})
            names |= sub_names
            if not sub_complete:
                complete = False
                hit_cycle = True
        names.discard("default")
        result = (names, complete)
        if not hit_cycle:
            self._cache[path] = result
        return result


SCAN_GLOBS = ("static/src/**/*.js", "static/tests/**/*.js")


def _scan_files(root: Path):
    for glob in SCAN_GLOBS:
        yield from root.rglob(glob)


def find_unsatisfied(roots: list[Path], addons_roots: list[Path]) -> list[Unsatisfied]:
    resolver = Resolver(addons_roots)
    found: list[Unsatisfied] = []
    for root in roots:
        for js_file in sorted(_scan_files(root)):
            if "/lib/" in str(js_file):
                continue
            try:
                source = strip_comments(js_file.read_text(encoding="utf-8"))
            except OSError, UnicodeDecodeError:  # pragma: no cover
                continue
            for brace_body, spec in NAMED_IMPORT_RE.findall(source):
                target = resolver.resolve(spec, js_file)
                if target is None:
                    continue
                available, complete = resolver.exports_of(target)
                if not complete:
                    continue
                found.extend(
                    Unsatisfied(str(js_file), spec, name, str(target))
                    for name in imported_names(brace_body)
                    if name not in available
                )
    return found


def discover_addons_roots() -> list[Path]:

    roots = [ROOT / "addons", ROOT / "odoo" / "addons"]
    roots.extend(repo for repo in default_consumer_repos() if repo.is_dir())
    seen: set[Path] = set()
    return [r for r in roots if r.is_dir() and not (r in seen or seen.add(r))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path, help="addons roots to SCAN")
    parser.add_argument(
        "--addons-root",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="addons root used to RESOLVE specifiers (defaults to the scanned roots)",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--list-roots", action="store_true", help="print scanned roots, then exit"
    )
    args = parser.parse_args(argv)

    scan_roots = args.roots or discover_addons_roots()
    if not scan_roots:
        parser.error(
            f"no addons root found around {ROOT} (siblings {SIBLING_REPOS_ROOT})"
        )
    addons_roots = args.addons_root or scan_roots
    if args.list_roots:
        for root in scan_roots:
            print(root)
        return 0

    scanned = sum(1 for root in scan_roots for _ in _scan_files(root))
    if not scanned:
        parser.error(
            f"no JS sources under {len(scan_roots)} scanned root(s) — "
            "the scan reached nothing"
        )

    unsatisfied = find_unsatisfied(scan_roots, addons_roots)
    if args.json:
        print(json.dumps([u.__dict__ for u in unsatisfied], indent=2))
    else:
        for item in unsatisfied:
            print(item)
        print(f"\n{len(unsatisfied)} unsatisfied named import(s)")
    return 1 if (unsatisfied and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
