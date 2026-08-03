"""Self-bridge gate: no source module may resolve itself through the loader.

A *bridge* is the shim the ESM pipeline generates so a native module can reach
a value the loader holds (``odoo/tools/assets/esm_graph.py::_bridge_module_source``,
whose shape ``@web/core/module_bridge`` documents)::

    const _m = odoo.loader.modules.get("@web/some/module");
    const _d = _m?.default ?? _m;
    export default _d;
    const _e0 = _m?.thing;
    export { _e0 as thing };

Bridges are built at bundle time and served from ``/web/assets/esm/bridges/``.
They are never checked in. When one is written over the source file it was
generated *from*, the specifier it reads is the module's own: the file resolves
itself, ``_m`` is the module still being defined, and **every export it names
comes out ``undefined``**. Consumers import successfully and call nothing.

This happened on 2026-08-03. Four files under ``addons/web/static/src`` were
overwritten with their own generated bridge — three dropdown behaviours and
``web_vitals_service`` — during work on the bundling code that emits them. The
web client stopped rendering its navbar, and 320 Hoot tests failed across
``@web/fields`` and ``@web/ui``.

**Nothing in this directory could see it**, and the reasons are structural
rather than accidental — every gate here ran green on that tree, along with all
299 tests in this directory:

* ``named_export_coherence`` asks whether an imported *name* is exported. A
  bridge re-exports every name it replaced, so the answer stayed yes. Names
  survive; only the values behind them are gone.
* ``js_public_surface`` compares the exported surface against
  ``public_surface_web.txt`` and reported it unchanged, for the same reason.
* ``js_layer_check``, ``js_cycle_check`` and ``js_layer_cohesion`` reason about
  the import graph. A bridge imports nothing, so it has no edges to fault — it
  is *maximally* clean by every graph measure.
* ``js_import_resolution`` checks that specifiers name real files. A bridge
  contains no specifiers, so there was nothing to check.

Every one of those is right about its own contract. The property none of them
holds is that a module still *evaluates to* something.

Contract, over ``static/src`` of every addon:

    No file reads ``odoo.loader.modules.get()`` on its own module specifier.

Limits, stated so a green result is not read as more than it is:

* Only self-reference is faulted. Reading the loader for *another* module is a
  legitimate dynamic lookup — ``html_editor``'s ``html_upgrade_manager.js``
  does it — and a bridge to another module, while still not something to check
  in, cannot be told apart from that by shape alone.
* Only literal arguments are seen. ``get(module)`` where ``module`` is a
  variable is out of scope, and is what the legitimate call sites use.
* It proves a module is not circular through the loader, not that its exports
  are non-``undefined`` at runtime. Nothing static can prove that.

The tree measured zero when this was written, so the gate is absolute: there is
no known-violations list, because a pin here would be a resting place for
exactly the bug it exists to catch. Its non-vacuity is carried by
``test_js_self_bridge.py``, which runs it against synthetic trees.

Usage::

    python tooling/architecture/js_self_bridge.py            # report
    python tooling/architecture/js_self_bridge.py --check    # exit 1 on any
    python tooling/architecture/js_self_bridge.py --json
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_import_resolution import EXCLUDED_PARTS, addon_static_dirs
from js_layer_check import ROOT

# `odoo.loader.modules.get("<literal>")`, tolerating the whitespace a formatter
# may introduce around the member accesses. A non-literal argument is
# deliberately not matched — see *Limits* in the module docstring.
BRIDGE_CALL = re.compile(
    r"""odoo\s*\.\s*loader\s*\.\s*modules\s*\.\s*get\s*\(\s*(['"])(?P<spec>[^'"]+)\1"""
)


def _rel(path: Path, root: Path) -> str:
    """Path relative to ``root`` when it is inside it, absolute otherwise."""
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class SelfBridge:
    file: str
    line: int
    specifier: str

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}\n"
            f"      resolves its own specifier {self.specifier} — "
            f"every export is undefined"
        )


def own_specifiers(path: Path, addon: str, static: Path) -> set[str]:
    """Every specifier that names ``path`` itself.

    Normally one. A file at ``a/index.js`` gets two, because the loader's
    lookup accepts both ``@addon/a/index`` and ``@addon/a`` for it.
    """
    stem = path.relative_to(static / "src").as_posix().removesuffix(".js")
    specs = {f"@{addon}/{stem}"}
    if stem.endswith("/index"):
        specs.add(f"@{addon}/{stem.removesuffix('/index')}")
    return specs


def find_self_bridges(
    statics: dict[str, Path] | None = None, root: Path = ROOT
) -> tuple[list[SelfBridge], int, int]:
    """``(findings, files_scanned, loader_reads_seen)``.

    ``statics`` is a parameter rather than a call to ``addon_static_dirs()`` so
    the whole pipeline is exercisable against a synthetic tree. A gate whose
    only evidence is "it returns clean on the real tree" cannot distinguish
    working from scanning nothing.
    """
    statics = addon_static_dirs() if statics is None else statics
    findings: list[SelfBridge] = []
    scanned = 0
    reads = 0
    for addon, static in sorted(statics.items()):
        src = static / "src"
        if not src.is_dir():
            continue
        for path in sorted(src.rglob("*.js")):
            if EXCLUDED_PARTS.intersection(path.relative_to(src).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
                print(f"warning: could not read {path}: {exc}", file=sys.stderr)
                continue
            scanned += 1
            if "loader" not in text:  # cheap reject; the regex is the authority
                continue
            mine = own_specifiers(path, addon, static)
            for match in BRIDGE_CALL.finditer(text):
                reads += 1
                spec = match.group("spec").removesuffix(".js")
                if spec in mine:
                    findings.append(
                        SelfBridge(
                            file=_rel(path, root),
                            line=text.count("\n", 0, match.start()) + 1,
                            specifier=spec,
                        )
                    )
    return findings, scanned, reads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    findings, n_files, n_reads = find_self_bridges()

    if not n_files:
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        print(
            "error: no addon static/src trees found under the checkout", file=sys.stderr
        )
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS self-bridge check (drift-zero, no tolerated list)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} module(s) bridged to themselves.")
            print("A generated bridge was written over the source it came from:")
            print("the module resolves itself, so every export it names is")
            print("undefined. Restore the implementation from git.")
        else:
            print("\nNo module resolves itself through the loader. ✓")
        print(f"\nFiles scanned: {n_files}   literal loader reads: {n_reads}")

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
