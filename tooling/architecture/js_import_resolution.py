"""Import-resolution gate: every first-party specifier must name a real file.

An ES module whose specifier does not resolve never evaluates. For a test file
that means the suite registers **nothing** — `hoot <suite>` reports
``0 failed / 0 passed`` rather than an error, and a summed run simply reports a
smaller total. The failure is silent in exactly the places a test suite is
supposed to be loud.

This happened on 2026-08-02. Moving the field suites from
``tests/views/fields/`` to ``tests/fields/<category>/<widget>/`` put four of
them two directories deeper and two of them one, and their ``../../`` prefixes
were not repointed. Six suites and 96 tests stopped running on HEAD.

**Nothing already in place could see it**, and each for a structural reason
worth stating, because "add it to the existing gate" is the obvious response
and would not have worked:

* ``js_cycle_check`` walks ``static/src`` only — never ``static/tests`` — and
  its ``_resolve()`` returns ``None`` both for "not a first-party module" and
  for "file does not exist". It *must* conflate them: it only cares about
  first-party edges, so a specifier it cannot resolve is correctly none of its
  business. Something else has to assert those do not exist.
* ``js_layer_check`` reasons about the specifier's *shape* (which layer it
  names), never about whether the target is there.
* The typecheck locks pass the affected files because they are excepted, and
  the base ``tsc`` count sees the TS2307 only as +1 in a four-figure aggregate.
* ``js_suite_parity`` passes: the directories mirror correctly, which is all it
  checks. Directory parity is not the same property as a suite that loads.

Contract, over ``static/src`` **and** ``static/tests`` of every addon:

    Every specifier that names first-party code resolves to a file on disk.

First-party means a relative specifier, ``@<addon>/<path>`` (-> that addon's
``static/src``), or ``@<addon>/../<path>`` (-> its ``static/``, the form tests
use to reach ``@web/../tests/web_test_helpers``). Bare specifiers
(``@odoo/owl``, ``luxon``, ``chart.js``) resolve through the import map, not
the filesystem, and are out of scope — see *Limits* below.

There is **no known-violations list**: the tree measured zero across 6,283
files and 22,129 checkable specifiers when this was written, so the gate is
absolute. A pin list here would be a place for exactly the bug it exists to
catch to come to rest.

Limits, stated so the green result is not read as more than it is:

* Bare specifiers are unchecked. A broken ``@odoo/owl`` would be caught by the
  bundler, not here.
* Resolution mirrors the loader's file lookup (``x``, ``x.js``, ``x/index.js``).
  It does not evaluate the import map, so an addon absent from this checkout
  (an ``@<enterprise addon>/`` specifier) is skipped rather than failed — there
  is no way to tell a typo from a module that lives in a sibling repo.
* It says a file exists, not that it exports what the importer names. That is
  ``named_export_coherence``'s contract.

Usage::

    python tooling/architecture/js_import_resolution.py            # report
    python tooling/architecture/js_import_resolution.py --check    # exit 1 on any
    python tooling/architecture/js_import_resolution.py --json
"""

import argparse
import json
import posixpath
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_imports import collect_imports  # sys.path set by conftest.py
from js_layer_check import ROOT

ADDON_ROOTS: tuple[Path, ...] = (ROOT / "addons", ROOT / "odoo" / "addons")

# Vendored third-party bundles and pre-layering code are not governed. Mirrors
# js_cycle_check's set, for the same reason.
EXCLUDED_PARTS = frozenset({"lib", "legacy", "__pycache__", "node_modules"})

# Both trees are scanned. `tests` is the half js_cycle_check omits, and is
# where an unresolvable specifier is silent rather than loud.
SCANNED_SUBTREES = ("src", "tests")


def _rel(path: Path, root: Path) -> str:
    """Path relative to ``root`` when it is inside it, absolute otherwise."""
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class Unresolved:
    file: str
    line: int
    specifier: str
    tried: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}\n      {self.specifier}  ->  {self.tried} (missing)"


def addon_static_dirs() -> dict[str, Path]:
    """Addon technical name -> its ``static`` directory.

    An addon present under both roots resolves to the first root that has it,
    which is the precedence ``addons_path`` gives.
    """
    dirs: dict[str, Path] = {}
    for root in ADDON_ROOTS:
        if not root.is_dir():
            continue
        for addon in sorted(root.iterdir()):
            static = addon / "static"
            if static.is_dir() and addon.name not in dirs:
                dirs[addon.name] = static
    return dirs


def iter_source_files(statics: dict[str, Path]) -> list[tuple[str, Path]]:
    """``[(addon, path), ...]`` for every governed client-side JS file."""
    out: list[tuple[str, Path]] = []
    for addon, static in statics.items():
        for sub in SCANNED_SUBTREES:
            base = static / sub
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.js")):
                if EXCLUDED_PARTS.intersection(path.relative_to(base).parts):
                    continue
                out.append((addon, path))
    return out


def resolve_target(
    spec: str, path: Path, addon: str, statics: dict[str, Path]
) -> Path | None:
    """The file a first-party specifier names, or ``None`` if not first-party.

    Returning ``None`` means "out of scope", never "missing" — the caller
    checks existence. Keeping those two answers apart is the whole point of
    this gate; conflating them is what made the breach invisible elsewhere.
    """
    if spec.startswith("."):
        return Path(posixpath.normpath(posixpath.join(path.parent.as_posix(), spec)))
    if not spec.startswith("@"):
        return None  # bare package, resolved by the import map
    owner, _, rest = spec[1:].partition("/")
    if not rest:
        return None
    static = statics.get(owner)
    if static is None:
        return None  # an addon this checkout does not carry
    if rest.startswith("../"):
        return static / rest[3:]
    return static / "src" / rest


def exists(target: Path) -> bool:
    """The loader's lookup: exact, ``.js``, then ``/index.js``."""
    return (
        target.is_file()
        or target.with_name(target.name + ".js").is_file()
        or (target / "index.js").is_file()
    )


def find_unresolved(
    statics: dict[str, Path] | None = None, root: Path = ROOT
) -> tuple[list[Unresolved], int, int]:
    """``(findings, files_scanned, specifiers_checked)``.

    ``statics`` is a parameter rather than a call to ``addon_static_dirs()`` so
    the whole pipeline — walk, extract, resolve, report — is exercisable
    against a synthetic tree. A gate whose only test is "it returns clean on
    the real tree" cannot distinguish working from scanning nothing.
    """
    statics = addon_static_dirs() if statics is None else statics
    findings: list[Unresolved] = []
    files = iter_source_files(statics)
    checked = 0
    for addon, path in files:
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        for spec, lineno in collect_imports(src):
            target = resolve_target(spec, path, addon, statics)
            if target is None:
                continue
            checked += 1
            if not exists(target):
                findings.append(
                    Unresolved(
                        file=_rel(path, root),
                        line=lineno,
                        specifier=spec,
                        tried=_rel(target, root),
                    )
                )
    return findings, len(files), checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    findings, n_files, n_specs = find_unresolved()

    if not n_files:
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        print(
            f"error: no addon static trees found under {ADDON_ROOTS}", file=sys.stderr
        )
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS import-resolution check (drift-zero, no tolerated list)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} unresolvable first-party specifier(s).")
            print("An unresolvable specifier means the module never evaluates:")
            print("a test suite registers 0 tests and still exits 0.")
        else:
            print("\nEvery first-party specifier resolves. ✓")
        print(f"\nFiles scanned: {n_files}   specifiers checked: {n_specs}")

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
