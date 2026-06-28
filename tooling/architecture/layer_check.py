#!/usr/bin/env python3
"""Architectural layering checker for the Odoo framework core (``odoo/``).

This is a dependency-free (stdlib-only) enforcement tool for the layering
contracts documented in ``odoo/ARCHITECTURE.md`` and the ADRs under
``doc/adr/``. It is the mechanical counterpart to those docs: the docs explain
*why* the boundaries exist, this script guarantees they are not crossed.

Why a custom checker instead of ``import-linter``
-------------------------------------------------
The whole point of the fork's layering is that cross-layer references are
*allowed* when guarded by ``if TYPE_CHECKING:`` — that is how the layers stay
acyclic while still sharing type information. Off-the-shelf import linters parse
every import, including those under ``TYPE_CHECKING``, so they would flag the
very pattern the architecture relies on. This checker walks the AST and skips
``TYPE_CHECKING`` blocks, counting only imports that execute at runtime. It also
resolves relative imports (which the fork uses pervasively — ``ruff`` ``TID252``
is intentionally disabled), so ``from ..models import X`` inside
``orm/fields/base.py`` is correctly understood as a runtime dependency on
``odoo.orm.models``. The ``from <pkg> import <submodule>`` form (e.g.
``from .. import models`` / ``from odoo import models``) is resolved to the
submodule, not just the package, and string-literal dynamic imports
(``importlib.import_module("...")`` / ``__import__("...")``) are checked like
static ones. Non-literal dynamic targets cannot be resolved statically and are
out of scope.

Usage
-----
    python tooling/architecture/layer_check.py            # human-readable report
    python tooling/architecture/layer_check.py --check    # CI mode, exit 1 on any violation
    python tooling/architecture/layer_check.py --json     # machine-readable

The contracts are intentionally limited to the load-bearing, verified
boundaries (see ``CONTRACTS`` below). New contracts should be added only for
invariants the team is prepared to keep at zero violations.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Repo root = the directory that contains the ``odoo/`` package. This file lives
# at ``<root>/tooling/architecture/layer_check.py``.
ROOT = Path(__file__).resolve().parent.parent.parent
PKG_ROOT = ROOT / "odoo"


@dataclass(frozen=True)
class Contract:
    """A "forbidden import" rule: files under ``source`` may not import ``forbidden``.

    Matching is by dotted-path prefix. A target import is a violation when it
    matches a ``forbidden`` prefix and does *not* match any ``allow`` prefix.
    """

    name: str
    source: tuple[str, ...]
    forbidden: tuple[str, ...]
    allow: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class Known:
    """A pre-existing, *tolerated* violation pinned with its remediation.

    The gate is drift-zero by design: any import that is not on this list fails
    immediately. Entries here are visible technical debt, each with a tracked
    fix. Removing the underlying import should also remove its entry.
    """

    module: str  # dotted-path prefix of the offending module
    imports: str  # dotted-path prefix of the tolerated import
    reason: str


# Known, tolerated boundary exceptions. Each would be real debt with a
# documented remediation; see the "Known boundary exceptions" section of
# odoo/ARCHITECTURE.md.
#
# The framework core currently has NONE — all eight boundaries are clean at zero:
#   * RESOLVED 2026-06: the ESM/esbuild asset pipeline was relocated from libs/
#     to odoo/tools/assets/ (ADR-0004).
#   * RESOLVED 2026-06: libs/filesystem/osutil.py no longer imports odoo.release
#     (the service name is passed in by the caller) (ADR-0004).
#   * RESOLVED 2026-06: the Layer-1 -> Layer-2 deferred BaseModel imports in
#     orm/domain/ast.py, orm/fields/relational.py and orm/fields/base.py (the
#     bottom-of-file ``from .. import models`` used by determine()/__set_name__)
#     were replaced by the injection seam orm/_recordset.py (ADR-0001). The last
#     of these was invisible to an earlier version of this checker, which
#     resolved ``from .. import models`` to the package ``odoo.orm`` and dropped
#     the submodule name; visit_ImportFrom now emits ``<base>.<name>`` so the
#     ``from <pkg> import <submodule>`` and ``from odoo import <shim>`` forms are
#     caught, and the seam modules themselves are now in a contract source set.
KNOWN_VIOLATIONS: tuple[Known, ...] = ()


# The verified, load-bearing architectural invariants of the framework core.
# Each one corresponds to an ADR; keep this list and doc/adr/ in sync.
CONTRACTS: tuple[Contract, ...] = (
    Contract(
        name="libs-is-dependency-free",
        source=("odoo.libs",),
        forbidden=("odoo",),
        allow=("odoo.libs",),
        rationale=(
            "odoo/libs/ is the home for dependency-free utilities. It must not "
            "import the Odoo framework (orm, tools, http, ...) so it stays "
            "reusable and testable in isolation. See ADR-0004."
        ),
    ),
    Contract(
        name="db-is-orm-agnostic",
        source=("odoo.db",),
        forbidden=("odoo.orm", "odoo.models", "odoo.fields", "odoo.api"),
        allow=("odoo.libs",),
        rationale=(
            "The db/ package (the decomposed sql_db.py) connects to the ORM only "
            "through injected hooks (e.g. BaseCursor._flushing_savepoint_cls), "
            "never by importing it. See ADR-0003."
        ),
    ),
    Contract(
        name="orm-components-are-pure-python",
        source=("odoo.orm.components",),
        forbidden=("odoo",),
        allow=("odoo.orm.components", "odoo.libs"),
        rationale=(
            "FieldCache / ComputeEngine / UnitOfWork / ModelGraph must be "
            "testable without an Environment, Registry, or database. They take "
            "their collaborators by injection. See ADR-0002."
        ),
    ),
    Contract(
        name="orm-layer1-below-models-and-runtime",
        source=("odoo.orm.fields", "odoo.orm.domain"),
        # Forbid both the internal layers and their public shims: importing the
        # ``odoo.models`` / ``odoo.api`` façades pulls in Layer 2 / Layer 3 just
        # as surely as importing ``odoo.orm.models`` / ``odoo.orm.runtime``.
        forbidden=("odoo.orm.models", "odoo.orm.runtime", "odoo.models", "odoo.api"),
        allow=(),
        rationale=(
            "Fields (Layer 1) and domains (Layer 1) sit below models (Layer 2) "
            "and runtime (Layer 3). Crossing this at runtime would reintroduce "
            "the import cycles the layering exists to prevent. See ADR-0001."
        ),
    ),
    Contract(
        name="orm-layer0-is-foundational",
        source=(
            "odoo.orm.primitives",
            "odoo.orm.parsing",
            "odoo.orm.validation",
            "odoo.orm.constants",
            "odoo.orm._typing",
        ),
        forbidden=(
            "odoo.orm.fields",
            "odoo.orm.domain",
            "odoo.orm.models",
            "odoo.orm.runtime",
            "odoo.orm.components",
            # public shims for the higher layers
            "odoo.fields",
            "odoo.models",
            "odoo.api",
        ),
        allow=(),
        rationale=(
            "Layer 0 (primitives, parsing, validation, constants, _typing) is the "
            "zero-dependency foundation: it may not import any higher ORM layer "
            "(nor its public shims odoo.fields / odoo.models / odoo.api). "
            "See ADR-0001."
        ),
    ),
    Contract(
        name="orm-models-below-runtime",
        source=("odoo.orm.models",),
        forbidden=("odoo.orm.runtime",),
        allow=(),
        rationale=(
            "Models (Layer 2) sit below the runtime (Layer 3: Environment, "
            "Registry, Transaction). Layer 3 builds on Layer 2, not the reverse. "
            "See ADR-0001."
        ),
    ),
    Contract(
        name="facade-boundary",
        # Addon code is the largest consumer of the ORM and the reason the public
        # façades exist. It must reach the ORM only through odoo.api / odoo.fields
        # / odoo.models (which are NOT under odoo.orm, hence not forbidden here),
        # so the ORM's internal layout can evolve without breaking addons. Imports
        # guarded by ``if TYPE_CHECKING:`` are exempt (they never execute and
        # create no runtime coupling), consistent with every other contract.
        #
        # Two physical addon trees live under this checkout and BOTH are in scope:
        #   * ``odoo/addons/``  — module name ``odoo.addons.*`` (framework + base).
        #   * ``addons/``       — module name ``addons.*`` (the bundled business
        #     addons, mounted at ``odoo.addons.*`` at runtime by the addons-path
        #     loader). It was previously unscanned, which let real leaks such as
        #     ``addons/resource/models/*.py`` import ``odoo.orm._typing`` directly.
        source=("odoo.addons", "addons"),
        forbidden=("odoo.orm",),
        allow=(),
        rationale=(
            "Addon and application code imports model features from the public "
            "façades (odoo.api, odoo.fields, odoo.models), never from odoo.orm.* "
            "internals. This is the boundary the whole façade strategy rests on: "
            "it keeps the ORM free to evolve behind a stable public surface. "
            "See ADR-0008."
        ),
    ),
    Contract(
        name="orm-seams-stay-below-models-and-runtime",
        # The cross-cutting seam modules that sit directly under odoo.orm and
        # were previously outside every contract's source set. _recordset.py is
        # the Layer-1 inversion point (ADR-0001) whose entire purpose is to let
        # Layer 1 recognise recordsets WITHOUT importing the model layer; a
        # runtime ``from .models import BaseModel`` here re-creates the very
        # cycle it exists to break. decorators.py (@api.depends, ...) is
        # likewise Layer-1-and-below by construction.
        source=("odoo.orm._recordset", "odoo.orm.decorators"),
        forbidden=("odoo.orm.models", "odoo.orm.runtime", "odoo.models", "odoo.api"),
        allow=(),
        rationale=(
            "The Layer-1 recordset injection seam (orm/_recordset.py) and the "
            "@api decorators must not import the model (Layer 2) or runtime "
            "(Layer 3) layers at runtime. The seam exists precisely to break "
            "that cycle (ADR-0001); enforcing it keeps the seam honest."
        ),
    ),
)


@dataclass
class Violation:
    contract: str
    module: str
    imports: str
    path: str
    lineno: int


@dataclass
class _ImportCollector(ast.NodeVisitor):
    """Collect runtime imports from a module, skipping ``TYPE_CHECKING`` blocks."""

    module: str  # dotted path of the file being parsed, e.g. odoo.orm.fields.base
    is_init: bool = False  # True for __init__.py (its __package__ == module)
    found: list[tuple[str, int]] = field(default_factory=list)

    def _resolve_relative(self, node_module: str | None, level: int) -> str:
        # Resolve ``from ...x import y`` against this file's ``__package__``,
        # mirroring Python's own semantics. For a package's __init__.py,
        # __package__ is the package itself; for a regular module it is the
        # parent package. A relative import of ``level`` then strips
        # ``level - 1`` further components.
        base = self.module if self.is_init else self.module.rsplit(".", 1)[0]
        for _ in range(level - 1):
            base = base.rsplit(".", 1)[0] if "." in base else ""
        if node_module:
            return f"{base}.{node_module}" if base else node_module
        return base

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.found.append((alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            base = self._resolve_relative(node.module, node.level)
        else:
            base = node.module or ""
        if base:
            self.found.append((base, node.lineno))
        # ``from <pkg> import <name>`` may bind a *submodule* ``<name>`` whose
        # real dotted path is ``<base>.<name>``. The bare ``<base>`` target
        # hides it, so ``from .. import models`` and ``from odoo import models``
        # would slip past a contract that forbids ``odoo.orm.models`` /
        # ``odoo.models``. Emit the submodule path as well. (For a plain symbol
        # import the dotted path matches no forbidden *package* prefix, so this
        # is a no-op for ordinary names.)
        if base:
            for alias in node.names:
                if alias.name != "*":
                    self.found.append((f"{base}.{alias.name}", node.lineno))

    def visit_If(self, node: ast.If) -> None:
        # Skip the body of ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:``;
        # those imports never execute. Still inspect the ``else`` branch.
        if _is_type_checking_test(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Dynamic imports execute at runtime and must be checked like static
        # ones: ``importlib.import_module("odoo.orm.runtime")``,
        # ``import_module("...")`` and ``__import__("odoo.orm.models")``. Only a
        # string-*literal* target can be resolved statically; a variable or
        # expression argument is left to review (the checker cannot know its
        # value). Relative dynamic imports (a leading-dot target) are likewise
        # not resolved here.
        func = node.func
        callee = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if callee in ("import_module", "__import__") and node.args:
            arg = node.args[0]
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and not arg.value.startswith(".")
            ):
                self.found.append((arg.value, node.lineno))
        self.generic_visit(node)


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def module_name_for(path: Path) -> str:
    """Dotted module path for a file under the repo root (``odoo/...``)."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _matches(dotted: str, prefixes: tuple[str, ...]) -> bool:
    return any(dotted == p or dotted.startswith(p + ".") for p in prefixes)


def _is_test_file(path: Path) -> bool:
    # Tests legitimately import across any boundary (fixtures, bootstrap, etc.).
    return (
        "tests" in path.parts
        or path.name == "conftest.py"
        or path.name.startswith("test_")
    )


def iter_source_files() -> list[Path]:
    source_prefixes = {p for c in CONTRACTS for p in c.source}
    # Translate dotted source prefixes to directories to avoid walking the whole
    # tree (odoo/addons/ alone is enormous and out of scope).
    roots = sorted({ROOT.joinpath(*p.split(".")) for p in source_prefixes})
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
        elif root.with_suffix(".py").is_file():
            files.append(root.with_suffix(".py"))
    return [
        f for f in files
        if "__pycache__" not in f.parts and not _is_test_file(f)
    ]


def _is_known(module: str, target: str) -> bool:
    return any(
        _matches(module, (k.module,)) and _matches(target, (k.imports,))
        for k in KNOWN_VIOLATIONS
    )


def check() -> tuple[list[Violation], list[Violation]]:
    """Return ``(new_violations, known_violations)``."""
    new: list[Violation] = []
    known: list[Violation] = []
    for path in iter_source_files():
        module = module_name_for(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        collector = _ImportCollector(module=module, is_init=path.name == "__init__.py")
        collector.visit(tree)
        for contract in CONTRACTS:
            if not _matches(module, contract.source):
                continue
            for target, lineno in collector.found:
                if not _matches(target, contract.forbidden):
                    continue
                if _matches(target, contract.allow):
                    continue
                # A file may legitimately import a sibling within its own source
                # subtree (e.g. odoo.orm.fields importing odoo.orm.fields.base);
                # that is never a layering violation.
                if _matches(target, contract.source):
                    continue
                v = Violation(
                    contract=contract.name,
                    module=module,
                    imports=target,
                    path=str(path.relative_to(ROOT)),
                    lineno=lineno,
                )
                (known if _is_known(module, target) else new).append(v)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on any NEW violation")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    new, known = check()

    if args.json:
        print(json.dumps(
            {"new": [v.__dict__ for v in new], "known": [v.__dict__ for v in known]},
            indent=2,
        ))
    else:
        print("Architecture layering check")
        print("=" * 64)
        for contract in CONTRACTS:
            n = sum(v.contract == contract.name for v in new)
            k = sum(v.contract == contract.name for v in known)
            status = "FAIL" if n else "ok"
            suffix = f" (+{k} known)" if k else ""
            print(f"[{status:>4}] {contract.name}: {n} new{suffix}")
        print("-" * 64)
        if new:
            print(f"\n{len(new)} NEW violation(s) — these fail the gate:\n")
            for v in new:
                print(f"  {v.path}:{v.lineno}")
                print(f"      {v.module}  ->  {v.imports}")
                print(f"      breaks contract: {v.contract}")
        else:
            print("\nNo new violations. All layering contracts hold. ✓")
        if known:
            print(f"\n{len(known)} known exception(s) tolerated (tracked debt):\n")
            for v in known:
                print(f"  {v.path}:{v.lineno}  {v.module} -> {v.imports}")
        print(f"\nFiles scanned: {len(iter_source_files())}")
        print(f"New: {len(new)}   Known/tolerated: {len(known)}")

    if args.check and new:
        print(f"\nFAILED: {len(new)} new layering violation(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
