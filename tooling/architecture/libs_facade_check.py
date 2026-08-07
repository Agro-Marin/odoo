#!/usr/bin/env python3
"""libs_facade_check.py — the ``odoo.libs`` façade boundary for addon code.

``facade-boundary`` (in ``layer_check.py``) stops addons importing
``odoo.orm.*``, so the ORM can be reorganised behind ``odoo.api`` /
``odoo.fields`` / ``odoo.models``. The identical argument applies to the
dependency-free utility layer, and nothing enforced it — so addon code had bound
itself to **124 leaf-module paths** inside ``odoo/libs/``, which silently made
that package's *file layout* public API. Renaming ``libs/web/urls.py`` broke 51
call sites; ``libs/numbers/float_utils.py``, 24.

THE RULE
--------

The public boundary of ``odoo/libs/`` is the **area** — ``odoo.libs`` itself and
its direct children (``odoo.libs.numbers``, ``odoo.libs.web``,
``odoo.libs.intervals``, …). Addon code imports an area; it does not reach past
one into the module that happens to implement it today::

    from odoo.libs.numbers import float_round  # OK — the area
    from odoo.libs.numbers.float_utils import float_round  # violation — a leaf
    from odoo.libs.intervals import Intervals  # OK — the area *is* a module

A top-level module such as ``odoo/libs/intervals.py`` is itself an area: there
is no package to hide behind, so the leaf is the boundary.

WHY THIS IS NOT A ``layer_check`` CONTRACT
------------------------------------------

It cannot be expressed in that model, and the reason is worth recording.
``_ImportCollector`` emits a synthetic ``<base>.<name>`` target for every
``from <base> import <name>``, so ``from odoo.libs.numbers import float_round``
yields ``odoo.libs.numbers.float_round``. By *name* that is indistinguishable
from ``odoo.libs.numbers.float_utils`` — one is a symbol, the other a module —
and ``Contract.allow`` is prefix-matched, so allowing the area would allow every
leaf under it. The discriminator is on disk: **does a module of that path
exist?** This checker asks the filesystem, which is why it is its own tool.

WHAT IT SCANS
-------------

Both addon trees inside this checkout, matching ``facade-boundary``'s scope
(``odoo/addons/`` and the repo-root ``addons/``), **plus every core package**:
``tools``, ``orm``, ``http``, ``modules``, ``service``, ``db``, ``cli``,
``tests``, ``_monkeypatches`` and ``upgrade_code``. ``odoo/libs`` itself is
excluded by design — an area importing its own leaves is how a package is
built. The authoritative list is ``SCANNED_TREES`` below, whose comment records
what each round of widening found; keep this paragraph in step with it.

``odoo/tools`` was outside the scope until it was measured: it is the single
heaviest consumer of ``odoo.libs`` in the repo, and it held 19 leaf imports —
four of them binding *private* names — while the gate reported the rule clean
everywhere else. A boundary enforced everywhere except where it is most often
crossed is not a boundary. Fixing those 19 also exposed two real gaps in the
areas themselves (``odoo.libs.email`` did not export ``getaddresses``;
``odoo.libs.text`` did not export ``reshape`` or its six public HTML regexes),
which is the other thing this gate is for: an area that a consumer must reach
past is an area missing an export.

Sibling checkouts (enterprise, agromarin) are separate repositories and out of
scope — they carry their own copy of this gate's rule via
``cross_repo_coherence.py``.

Test files are scanned like any other: a test that binds a leaf path pins the
layout just as firmly as production code does. Current exceptions are pinned in
``KNOWN_VIOLATIONS`` below.

USAGE
-----

  python tooling/architecture/libs_facade_check.py            # report
  python tooling/architecture/libs_facade_check.py --check    # CI: exit 1
  python tooling/architecture/libs_facade_check.py --json

exit 0 — no new violations
exit 1 — a new leaf-module import from addon code
exit 2 — usage error
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="libs_facade_check")
LIBS = REPO_ROOT / "odoo" / "libs"

#: Trees whose imports of ``odoo.libs`` must name an *area*, never a leaf.
#:
#: The two addon trees are the same scope as ``facade-boundary``.  ``odoo/tools``
#: is here because it is the single heaviest consumer of ``odoo.libs`` in the
#: repo, and the rationale this gate was built on -- renaming
#: ``libs/web/urls.py`` broke 51 call sites -- applies to it verbatim.  Leaving
#: it out meant the gate enforced the rule everywhere except where it was most
#: often broken, including four imports of *private* names that no area exports.
#:
#: ``odoo/orm``, ``odoo/http``, ``odoo/modules`` and ``odoo/service`` were added
#: next: the gate reported green while nine leaf imports sat unpinned in ORM hot
#: paths (``fields/temporal.py``, ``runtime/environment.py``, …), exactly the
#: hazard it exists to catch.  All nine were reachable through their area and
#: were rewritten to name it; one under-export (``datetime.country_timezones``)
#: was added to the area; the sole genuine leaf import is the vendored
#: ``_vendor.useragents``, pinned in ``KNOWN_VIOLATIONS`` like its siblings.
#:
#: ``db``, ``cli``, ``tests``, ``_monkeypatches`` and ``upgrade_code`` complete
#: the core.  Measured at **0 leaf imports** when they were added, so unlike the
#: two rounds above this closes no existing hole -- it stops the next one.  The
#: gate's own argument applies: a boundary that holds only where someone
#: remembered to look is not a boundary, and every previous extension was
#: prompted by discovering violations in a tree nobody had scanned.
#:
#: ``odoo/libs`` itself is deliberately absent: an area importing its own leaf
#: modules is how a package is built, not a violation.  The six top-level
#: modules (``logutils.py``, ``exceptions.py``, ``release.py``, ``init.py``,
#: ``__main__.py``, ``_testing_bootstrap.py``) are also unscanned -- entries
#: here are directories, walked with ``rglob`` -- and were measured clean at the
#: same time.
SCANNED_TREES: tuple[Path, ...] = (
    REPO_ROOT / "odoo" / "addons",
    REPO_ROOT / "addons",
    REPO_ROOT / "odoo" / "tools",
    REPO_ROOT / "odoo" / "orm",
    REPO_ROOT / "odoo" / "http",
    REPO_ROOT / "odoo" / "modules",
    REPO_ROOT / "odoo" / "service",
    REPO_ROOT / "odoo" / "db",
    REPO_ROOT / "odoo" / "cli",
    REPO_ROOT / "odoo" / "tests",
    REPO_ROOT / "odoo" / "_monkeypatches",
    REPO_ROOT / "odoo" / "upgrade_code",
    # The public re-export shims. One line in any of them is enough to make a
    # libs leaf path part of the framework's public API -- the widest possible
    # blast radius for the exact failure this gate exists to prevent.
    REPO_ROOT / "odoo" / "api",
    REPO_ROOT / "odoo" / "fields",
    REPO_ROOT / "odoo" / "models",
)

#: Backwards-compatible alias: the addon-only subset this gate started with.
ADDON_TREES: tuple[Path, ...] = SCANNED_TREES[:2]


@dataclass(frozen=True)
class Known:
    """A tolerated leaf import, pinned so it stays visible and cannot spread."""

    path: str  # repo-relative source file
    module: str  # the odoo.libs leaf module it imports
    reason: str


KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known(
        "odoo/addons/test_mimetypes/tests/test_guess_mimetypes.py",
        "odoo.libs.filesystem.mimetypes",
        "Imports _odoo_guess_mimetype, the pure-Python fallback deliberately "
        "kept out of the odoo.libs.filesystem façade: this suite exists to test "
        "it against the python-magic path, so it must name the implementation.",
    ),
    Known(
        "odoo/addons/test_http/utils.py",
        "odoo.libs._vendor.sessions",
        "SessionStore from the vendored werkzeug session code. _vendor is "
        "third-party source kept verbatim; giving it a curated façade would "
        "imply a stability promise the vendor makes, not us.",
    ),
    Known(
        "odoo/tools/sass_embedded.py",
        "odoo.libs._vendor.embedded_sass_pb2",
        "Generated protobuf bindings for the Dart Sass embedded protocol. Same "
        "reasoning as the other _vendor entry: the file is generated, not "
        "authored, and re-exporting its symbols through an area would put a "
        "curated name on a protobuf-versioned surface.",
    ),
    Known(
        "odoo/tools/mail.py",
        "odoo.libs.email.parsing",
        "_normalize_email, deliberately private: the public entry points are "
        "email_normalize/email_normalize_all, and tools/mail.py needs the "
        "un-guarded inner form. Exporting it would promote an implementation "
        "detail to API for one caller.",
    ),
    Known(
        "odoo/tools/template_inheritance.py",
        "odoo.libs.xml.template_inheritance",
        "_compile_xpath, deliberately private. tools/template_inheritance.py "
        "wraps the area's public apply_inheritance_specs/locate_node (both "
        "imported from the area) and additionally needs the raw xpath "
        "compiler to translate lxml errors into ValidationError.",
    ),
    Known(
        "odoo/http/wrappers.py",
        "odoo.libs._vendor.useragents",
        "UserAgent from the vendored werkzeug user-agent code. Same reasoning as "
        "the other _vendor entries: third-party source kept verbatim, with no "
        "curated area façade to promise stability the vendor does not.",
    ),
    Known(
        "odoo/orm/tests/test_sorted_multi_key.py",
        "odoo.libs._field_access._fallback",
        "Imports the pure-Python sort_ids_by_values fallback alongside the area's "
        "fast path to assert parity between them — the same test-the-"
        "implementation pattern as the test_guess_mimetypes entry, so it must "
        "name the fallback the area deliberately does not export.",
    ),
    Known(
        "odoo/http/tests/test_session_store.py",
        "odoo.libs._vendor.sessions",
        "_fs_transaction_suffix from the vendored werkzeug session store, needed "
        "to assert the tmp-file vacuum reaps orphans. Same _vendor reasoning as "
        "test_http/utils.py: the vendored source has no curated area façade.",
    ),
)


@dataclass
class Violation:
    path: str
    module: str
    lineno: int
    area: str


@dataclass
class Report:
    new: list[Violation] = field(default_factory=list)
    known: list[Violation] = field(default_factory=list)
    areas: set[str] = field(default_factory=set)
    scanned: int = 0

    @property
    def ok(self) -> bool:
        return not self.new


@lru_cache(maxsize=1)
def areas() -> frozenset[str]:
    """The public areas of ``odoo.libs``: the package and its direct children.

    Read from disk rather than hard-coded, so adding ``libs/<new_area>/`` does
    not require editing this gate — and so a *removed* area cannot linger here
    as a permanently-satisfied allowance.
    """
    found = {"odoo.libs"}
    for child in LIBS.iterdir():
        if child.name.startswith("__") or child.name == "tests":
            continue
        if child.is_dir() and (child / "__init__.py").is_file():
            found.add(f"odoo.libs.{child.name}")
        elif child.suffix == ".py":
            found.add(f"odoo.libs.{child.stem}")
    return frozenset(found)


@cache
def module_exists(dotted: str) -> bool:
    """Is ``dotted`` a real module/package under ``odoo/libs/``?"""
    rel = dotted.removeprefix("odoo.libs.").split(".")
    base = LIBS.joinpath(*rel)
    return (base / "__init__.py").is_file() or base.with_suffix(".py").is_file()


def imported_modules(tree: ast.AST) -> list[tuple[str, int]]:
    """Every ``odoo.libs*`` **module** an AST imports, with its line number.

    For ``from X import a, b`` the module is ``X``; the names are symbols and are
    not paths. ``import X.Y`` imports the module ``X.Y`` directly.
    """
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import inside an addon; never odoo.libs
            if not node.level and node.module and node.module.startswith("odoo.libs"):
                out.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            out.extend(
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name.startswith("odoo.libs")
            )
    return out


def _is_known(path: str, module: str) -> bool:
    return any(k.path == path and k.module == module for k in KNOWN_VIOLATIONS)


def check(files: list[Path] | None = None) -> Report:
    report = Report(areas=set(areas()))
    if files is None:
        files = [
            p
            for tree in SCANNED_TREES
            if tree.is_dir()
            for p in sorted(tree.rglob("*.py"))
            if "__pycache__" not in p.parts
        ]
    allowed = areas()
    for path in files:
        report.scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        for module, lineno in imported_modules(tree):
            if module in allowed:
                continue
            # Deeper than an area. If no module of that path exists it is not a
            # module import at all (a stale reference); report it either way,
            # since importing it would fail.
            rel = path.relative_to(REPO_ROOT).as_posix()
            area = ".".join(module.split(".")[:3])
            v = Violation(rel, module, lineno, area)
            (report.known if _is_known(rel, module) else report.new).append(v)
    return report


def _render(report: Report) -> str:
    lines = [
        "odoo.libs façade boundary",
        "=" * 64,
        f"addon files scanned: {report.scanned}",
        f"public areas of odoo.libs: {len(report.areas)}",
    ]
    if report.new:
        lines.append(f"\n{len(report.new)} NEW leaf-module import(s):")
        lines.extend(
            f"  {v.path}:{v.lineno}\n"
            f"      imports {v.module}\n"
            f"      use the area instead: {v.area}"
            for v in report.new
        )
    if report.known:
        lines.append(f"\n{len(report.known)} known import(s) tolerated (tracked debt):")
        lines.extend(
            f"  {v.path}:{v.lineno}  {v.module}"
            for v in sorted(report.known, key=lambda x: (x.path, x.lineno))
        )
    lines.append("")
    lines.append(
        "Addon code imports odoo.libs areas, not their internals. ✓"
        if report.ok
        else "FAILED: addon code reached past the odoo.libs façade."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate the odoo.libs façade.")
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "scanned": report.scanned,
                    "areas": sorted(report.areas),
                    "new": [
                        {"path": v.path, "line": v.lineno, "module": v.module}
                        for v in report.new
                    ],
                    "known": len(report.known),
                },
                indent=2,
            )
        )
    else:
        print(_render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
