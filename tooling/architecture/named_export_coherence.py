"""Named-export coherence gate: every ``import { x }`` must find an ``x``.

Companion to :mod:`cross_repo_coherence`, which catches whole-module removals
and states its own gap outright: *"a removed named export inside a file that
still exists is not detected"*. This gate closes it.

Under native ESM that gap is not a soft failure. A named import the target
module does not export is a **link-time SyntaxError**: the browser refuses the
whole module graph, so the entire asset bundle dies for every database that
installs the importing module. No JS test can catch it either, because no test
file gets to run -- the suite simply reports fewer tests than it should, which
reads as green.

Motivating incident (2026-07-28): ``@web/views/view_compiler`` renamed
``compileViewTemplates``/``useViewCompiler`` while ``web_gantt`` and
``hr_payroll`` still imported the old name. Both files existed, so
``cross_repo_coherence`` saw nothing; every ``@web`` suite failed to boot with
``does not provide an export named``.

Usage::

    python tooling/architecture/named_export_coherence.py           # report
    python tooling/architecture/named_export_coherence.py --check   # exit 1
    python tooling/architecture/named_export_coherence.py --json
    python tooling/architecture/named_export_coherence.py --list-roots

Scope note: it verifies what it can READ. A specifier pointing outside the
checked-out repos, or a re-export chain it cannot fully resolve, yields no
verdict rather than a guess -- a false positive in a blocking gate is worse
than a miss, because it teaches people to ignore the gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from cross_repo_coherence import SIBLING_REPOS_ROOT, default_consumer_repos
from js_layer_check import strip_comments

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# Located by marker, not by counting parents — see _repo_root.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="named_export_coherence")

#: ``import { a, b as c } from "@web/x/y";`` -- brace body plus specifier.
#: The optional leading group covers ``import Default, { a } from "..."``: the
#: default binding sits between ``import`` and the brace, and without it the
#: whole statement went unchecked. Zero such imports exist in-tree today, which
#: is precisely why it would have gone unnoticed the day one appeared.
NAMED_IMPORT_RE = re.compile(
    r"""import\s*(?:[A-Za-z_$][\w$]*\s*,\s*)?\{([^}]*)\}\s*from\s*["']([^"']+)["']"""
)
#: ``export { a, b as c } from "..."`` / ``export { a, b };``
NAMED_EXPORT_RE = re.compile(r"""export\s*\{([^}]*)\}""")
#: ``export function f`` / ``export class C`` / ``export const x`` (may be
#: indented). ``function\s*\*?`` so the generator star binds either way --
#: ``export function* g`` and ``export function *g`` are the same declaration,
#: and treating the second as no export at all would report every importer of
#: ``g`` as broken.
DECL_EXPORT_RE = re.compile(
    r"""^[ \t]*export\s+(?:async\s+)?"""
    # `function* g` and `function *g` are one declaration written two ways; the
    # star may take the whitespace from either side, so both spellings need
    # their own alternative rather than an optional `\*?` that then still
    # demands a space.
    r"""(?:function\s*\*\s*|function\s+|class\s+|const\s+|let\s+|var\s+)"""
    r"""([A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)
#: ``export const { Modal, Tooltip } = Bootstrap;`` / ``export const [a, b] = ...``
DESTRUCTURED_EXPORT_RE = re.compile(
    r"""^[ \t]*export\s+(?:const|let|var)\s*([{\[][\s\S]*?[}\]])\s*=""", re.MULTILINE
)
STAR_REEXPORT_RE = re.compile(r"""export\s*\*\s*from\s*["']([^"']+)["']""")
#: ``@web/core/x`` -> addon ``web``, subpath ``core/x``.
MODULE_SPEC_RE = re.compile(r"^@([a-z0-9_]+)/(.+)$")
#: One binding inside a destructuring pattern: ``a``, ``a: b``, ``a = d``.
BINDING_RE = re.compile(r"""([A-Za-z_$][\w$]*)\s*(?::\s*([A-Za-z_$][\w$]*))?""")

#: Scopes that are not addons (``@odoo/owl``, ``@odoo/hoot``...).
NON_ADDON_SCOPES = {"odoo", "web_tour_tests"}


@dataclass(frozen=True)
class Unsatisfied:
    """One named import with no matching export in the resolved module."""

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
    """Binding names introduced by a destructuring export pattern.

    ``@web/libs/bootstrap`` publishes all twelve Bootstrap components with one
    ``export const { Modal, Tooltip, ... } = Bootstrap;``. Understanding only
    ``export const <identifier>`` reports every importer of them as broken --
    20 false positives that would bury the real findings.
    """
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
            # ``a: b`` binds ``b``; a bare ``a`` binds ``a``.
            names.add(match.group(2) or match.group(1))
    return names


def imported_names(brace_body: str) -> list[str]:
    """The ORIGINAL (exported) names an import brace body requests."""
    names = []
    for part in brace_body.split(","):
        part = part.strip()
        if part:
            names.append(part.split(" as ")[0].strip())
    return [n for n in names if n and n != "default"]


#: An exported binding is a JS identifier. Verified against a real parser over
#: every module in this repo: all 5942 named exports are plain identifiers.
IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def exported_names(brace_body: str) -> set[str]:
    """The names an ``export { ... }`` clause publishes.

    Non-identifiers are dropped. ``NAMED_EXPORT_RE`` matches text, so it also
    fires inside a template literal that BUILDS an export statement --
    ``core/module_bridge.js:34`` does exactly that with
    ``lines.push(`export { ${aliases.join(", ")} };`)`` -- and the gate then
    believed the module published ``")`` and ``${aliases.join("``. Those are
    unimportable, so nothing broke; a template producing real identifiers would
    instead have made the gate miss a genuinely broken import.
    """
    names = set()
    for part in brace_body.split(","):
        part = part.strip()
        if part:
            # ``export { a as b }`` publishes ``b``.
            name = part.split(" as ")[-1].strip()
            if IDENTIFIER_RE.match(name):
                names.add(name)
    return names


class Resolver:
    """Maps module specifiers onto files across the checked-out repos."""

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
        """Resolve ``spec`` to a file, or ``None`` when it is out of scope.

        Relative specifiers resolve against ``importer``'s directory. Skipping
        them blinds the gate to whole modules: mail's public surface is a
        barrel of ``export * from "./record.js"``, so no ``@mail/...`` importer
        was verifiable until these resolved.
        """
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
        """``(names, complete)`` for ``path``, following ``export * from``.

        ``complete`` is False when a re-export target could not be read, so
        callers withhold judgement instead of reporting a false positive. A
        result computed inside an import CYCLE is never cached -- it is only
        valid for the branch that produced it.
        """
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


def find_unsatisfied(roots: list[Path], addons_roots: list[Path]) -> list[Unsatisfied]:
    """Every named import in ``roots`` with no matching export."""
    resolver = Resolver(addons_roots)
    found: list[Unsatisfied] = []
    for root in roots:
        for js_file in sorted(root.rglob("static/src/**/*.js")):
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
    """Every addons root reachable from this repo plus its sibling checkouts.

    Anchored on this file rather than on a hardcoded workspace layout: the same
    repo is ``addons/odoo`` for a developer and ``addons/core`` in CI, and a
    gate that cannot find its own inputs must say so rather than scan nothing
    and report success.
    """
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
    # Explicit scan roots also become the resolution universe unless told
    # otherwise: resolving an explicitly-scoped scan against the whole
    # workspace silently answered from a DIFFERENT copy of the module than the
    # one under test, so the gate verified something the caller never asked
    # about and reported it clean.
    addons_roots = args.addons_root or scan_roots
    if args.list_roots:
        for root in scan_roots:
            print(root)
        return 0

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
