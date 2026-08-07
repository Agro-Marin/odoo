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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# Located by marker, not by counting parents: a counted depth silently resolves
# to the wrong tree the moment a script moves, and this gate's whole value is
# that it scanned the tree it claims to have scanned.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="layer_check")
PKG_ROOT = ROOT / "odoo"


@dataclass(frozen=True)
class Contract:
    """A "forbidden import" rule: files under ``source`` may not import ``forbidden``.

    Matching is by dotted-path prefix. A target import is a violation when it
    matches a ``forbidden`` prefix and does *not* match any ``allow`` prefix.

    ``allow_exact`` exempts a module *itself* without exempting its subtree,
    which prefix matching cannot express: ``core-does-not-depend-on-addons``
    has to permit ``import odoo.addons`` (the namespace package, for ``__path__``
    discovery) while forbidding every ``odoo.addons.<module>`` under it. A
    prefix in ``allow`` would exempt both.
    """

    name: str
    source: tuple[str, ...]
    forbidden: tuple[str, ...]
    allow: tuple[str, ...]
    rationale: str
    allow_exact: tuple[str, ...] = ()


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


# Known, tolerated boundary exceptions; see the "Known boundary exceptions"
# section of odoo/ARCHITECTURE.md.
#
# The EIGHT ORIGINAL contracts are clean at zero and stay that way
# (test_the_eight_original_contracts_are_clean_at_zero):
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
#
# The NINTH, core-does-not-depend-on-addons (2026-08), starts with two pinned
# entries. Unlike the list above they are NOT debt with a tracked fix: the
# cron/job runner threads genuinely run before a registry exists (see
# _CRON_REASON). They are pinned rather than allow-listed so they stay scoped to
# odoo.service and stay visible in every report. The two inversions that WERE
# debt were fixed instead of pinned, in the commit that added the contract:
#   * MODULE_UNINSTALL_FLAG  addons/base/models/ir_model_common -> orm/primitives
#   * format_number & co.    addons/base/models/res_lang -> libs/locale/number_format

#: Core packages deliberately left OUT of ``core-does-not-depend-on-addons``.
#: Asserted by ``test_core_source_covers_every_core_package``, so a package can
#: only be missing on purpose.
CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT = frozenset(
    {
        # ``odoo.tests`` is the test *framework*, whose job is to drive
        # application code. ``tests/http.py`` reaches into ``odoo.addons.bus``
        # for websocket teardown, deferred AND guarded by
        # ``if "bus.bus" in self.env.registry:`` — i.e. it already treats the
        # addon as optional, which is the property the contract would be
        # enforcing. Bringing it in scope would buy a pinned exception and no
        # safety.
        "tests",
    }
)

_CRON_REASON = (
    "Deliberate, and not scheduled for removal. The cron/job runner threads call "
    "IrCron._process_jobs(db_name) / IrJob._process_jobs(db_name) -- @staticmethod "
    "entry points that open their own cursor because they run BEFORE a registry "
    "exists for that database, so there is no env to route through. Both imports "
    "are deferred to call time (base models must not load at service import "
    "time), and the audit that added this contract verified there is no override "
    "of _process_jobs anywhere in odoo/enterprise/agromarin, so binding to the "
    "definition class hides nothing. Pinned rather than fixed: the honest "
    "alternative is a registered callback the base module fills in at load, which "
    "buys indirection and no decoupling."
)

KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known(
        module="odoo.service",
        imports="odoo.addons.base.models.ir_cron",
        reason=_CRON_REASON,
    ),
    Known(
        module="odoo.service",
        imports="odoo.addons.base.models.ir_job",
        reason=_CRON_REASON,
    ),
)


# The verified, load-bearing architectural invariants of the framework core.
# Each one corresponds to an ADR; keep this list and doc/adr/ in sync.
CONTRACTS: tuple[Contract, ...] = (
    Contract(
        name="libs-is-dependency-free",
        source=("odoo.libs",),
        forbidden=("odoo",),
        allow=("odoo.libs",),
        rationale=(
            "odoo/libs/ is the home for Odoo-framework-free utilities. The "
            "invariant is 'imports no odoo.* (except odoo.libs)', NOT "
            "'dependency-free' in the literal sense — libs/ freely uses "
            "third-party packages (lxml, PIL, babel, markupsafe) and the "
            "odoo_rust extension. What it must not import is the framework "
            "(orm, tools, http, ...), so it stays reusable and testable in "
            "isolation. The contract name is kept for continuity; read it as "
            "'libs-is-odoo-free'. See ADR-0004."
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
        name="core-does-not-depend-on-addons",
        # The mirror image of ``facade-boundary``. That one stops addons reaching
        # into ORM internals; nothing stopped the *framework* taking a dependency
        # on a specific addon module, which is the more damaging direction: it
        # makes the core un-loadable without an addon, and inverts the layering
        # (``addons/base`` is a consumer of the framework, not a dependency of
        # it).
        #
        # ``source`` names the core packages explicitly rather than the ``odoo``
        # prefix, because ``odoo`` would also match ``odoo.addons`` and the
        # own-subtree rule in ``check()`` would then exempt every import. A
        # self-test (``test_core_source_covers_every_core_package``) asserts this
        # list stays complete, so a new top-level core package cannot silently
        # escape the contract.
        #
        # ``odoo.addons`` itself is allowed: importing the *namespace package*
        # for ``__path__`` manipulation is how addon discovery works
        # (``modules/module.py``, ``tools/files.py``, the CLI). That imports no
        # addon code. Only ``odoo.addons.<something>`` is forbidden.
        source=(
            "odoo._monkeypatches",
            "odoo.api",
            "odoo.cli",
            "odoo.db",
            "odoo.fields",
            "odoo.http",
            "odoo.libs",
            "odoo.models",
            "odoo.modules",
            "odoo.orm",
            "odoo.service",
            "odoo.tools",
            "odoo.upgrade_code",
        ),
        forbidden=("odoo.addons",),
        allow=(),
        # ``odoo.addons`` — the namespace package, for __path__ discovery.
        # ``odoo.addons.__path__`` — the same thing via
        # ``from odoo.addons import __path__``, which visit_ImportFrom renders as
        # ``<base>.<name>``. Both import the namespace, never an addon.
        allow_exact=("odoo.addons", "odoo.addons.__path__"),
        rationale=(
            "The framework core must be importable without any addon. A core "
            "module that imports odoo.addons.<module> inverts the layering and "
            "makes the framework depend on its own consumer. Reach addon "
            "behaviour through the registry (env['ir.cron']) or move the shared "
            "definition down into the core, as MODULE_UNINSTALL_FLAG "
            "(-> odoo.orm.primitives) and format_number "
            "(-> odoo.libs.locale.number_format) were. Bare ``import "
            "odoo.addons`` for __path__ discovery is fine and not matched here."
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
    Contract(
        name="db-resilience-below-connectivity",
        # ARCHITECTURE.md has always drawn db/ as [connectivity] + [resilience]
        # (now + [foundation]), with an explicit note that a bracketed name is a
        # "logical grouping, not a directory". subsystem_map_check.py verifies
        # the listed modules EXIST; nothing verified the direction between the
        # groups, so the structure was documentation only.
        #
        # Measured before this contract landed: connectivity -> resilience 6
        # runtime edges (pool -> budget/leaks/reaper/stats, cursor -> metrics),
        # resilience -> connectivity exactly 1 -- metrics -> errors. That single
        # back-edge was a MIS-GROUPING, not a cycle: errors.py (like dsn.py and
        # utils.py) imports nothing else in db/ and is used by both tiers, i.e.
        # it is foundation, not connectivity. Splitting [foundation] out of
        # [connectivity] leaves this contract clean at zero.
        source=(
            "odoo.db.breaker",
            "odoo.db.lag",
            "odoo.db.budget",
            "odoo.db.leaks",
            "odoo.db.reaper",
            "odoo.db.metrics",
            "odoo.db.stats",
        ),
        forbidden=(
            "odoo.db.pool",
            "odoo.db.cursor",
            "odoo.db.ddl",
            "odoo.db.schema",
            "odoo.db.savepoint",
            "odoo.db.schema_cache",
            "odoo.db.bulk",
            "odoo.db.lifecycle",
        ),
        allow=(),
        rationale=(
            "The resilience tier (breaker, lag, budget, leaks, reaper, metrics, "
            "stats) is instrumentation and policy ABOUT connections; the "
            "connectivity tier owns them. Connectivity calls into resilience "
            "(pool -> budget/leaks/reaper/stats, cursor -> metrics), never the "
            "reverse, so resilience stays independently testable without "
            "standing up a pool or a cursor. Shared leaf helpers belong in the "
            "[foundation] tier (errors, dsn, utils), which both may import."
        ),
    ),
    Contract(
        name="http-features-below-serving",
        # Same argument as db-resilience-below-connectivity, for the other flat
        # package the map draws in brackets. Measured before this landed:
        # serving -> features 22 runtime edges, features -> serving exactly 1
        # (helpers -> core). Again a mis-grouping rather than a cycle: helpers.py
        # imports core and is imported by dispatcher/_serve/request_class, all
        # [serving] -- it IS a serving module and the map now files it there.
        #
        # _protocols.py's imports of dispatcher/session/wrappers are under
        # ``if TYPE_CHECKING:`` and so are exempt here, exactly as they are for
        # the ORM layer contracts: they never execute.
        source=(
            "odoo.http.openapi",
            "odoo.http._params",
            "odoo.http.geoip",
            "odoo.http.constants",
            "odoo.http.exceptions",
            "odoo.http._protocols",
        ),
        forbidden=(
            "odoo.http.application",
            "odoo.http.dispatcher",
            "odoo.http.routing",
            "odoo.http.session",
            "odoo.http.request_class",
            "odoo.http._serve",
            "odoo.http._response",
            "odoo.http.wrappers",
            "odoo.http.stream",
            "odoo.http._csrf",
            "odoo.http.controller",
            "odoo.http.core",
            "odoo.http.helpers",
        ),
        allow=(),
        rationale=(
            "The [features] modules (OpenAPI generation, typed-route parameter "
            "coercion, geoip, and the shared constants/exceptions/protocols) "
            "describe or decorate the request pipeline; the [serving] modules "
            "run it. Features must not import serving, so the pipeline can be "
            "reasoned about — and the OpenAPI generator run — without dragging "
            "in the dispatcher and session machinery."
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


#: ``odoo/tests/`` is NOT tests. It is the shipped test *framework* --
#: ``TransactionCase``, ``HttpCase``, ``ChromeBrowser``, the loader and the tag
#: selector -- 17 modules imported by every addon suite in the workspace. A
#: directory-name rule ("any path with a ``tests`` component") swallowed it whole,
#: which made those modules invisible to every contract.
#:
#: That mattered for a specific, non-obvious reason. ``odoo.tests`` is
#: deliberately absent from ``core-does-not-depend-on-addons``'s ``source``, and
#: ``CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT`` records that so
#: ``test_core_source_covers_every_core_package`` can hold the list complete.
#: The intended way to revoke the exemption is to drop ``tests`` from that
#: frozenset, watch the self-test fail, and add ``odoo.tests`` to ``source``.
#: Before this fix, doing all of that correctly still enforced *nothing*: the
#: files were dropped here, one step earlier, so the contract came back green
#: over code it had never read. An exemption you cannot revoke is worse than one
#: that is merely wide, because it looks revocable.
_CORE_TEST_FRAMEWORK_PACKAGE = ("odoo", "tests")


def _is_test_file(path: Path) -> bool:
    # Tests legitimately import across any boundary (fixtures, bootstrap, etc.).
    # ``path`` may be absolute (the tree walk) or relative (callers and tests),
    # so anchor on ROOT only when it actually applies.
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        parts = path.parts
    if parts[: len(_CORE_TEST_FRAMEWORK_PACKAGE)] == _CORE_TEST_FRAMEWORK_PACKAGE:
        # Inside the test framework, only its own tests are test files.
        return path.name.startswith("test_") or path.name == "conftest.py"
    return (
        "tests" in parts or path.name == "conftest.py" or path.name.startswith("test_")
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
    return [f for f in files if "__pycache__" not in f.parts and not _is_test_file(f)]


def _is_known(module: str, target: str) -> bool:
    return any(
        _matches(module, (k.module,)) and _matches(target, (k.imports,))
        for k in KNOWN_VIOLATIONS
    )


def check(files: list[Path] | None = None) -> tuple[list[Violation], list[Violation]]:
    """Return ``(new_violations, known_violations)``.

    ``files`` lets a caller that already walked the tree pass the result in;
    the walk spans both addon trees (6193 files) and ``main`` used to repeat it
    purely to print a count.
    """
    new: list[Violation] = []
    known: list[Violation] = []
    for path in files if files is not None else iter_source_files():
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
                if target in contract.allow_exact:
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
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW violation"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    new, known = check(files)

    if args.json:
        print(
            json.dumps(
                {
                    "new": [v.__dict__ for v in new],
                    "known": [v.__dict__ for v in known],
                },
                indent=2,
            )
        )
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
        print(f"\nFiles scanned: {len(files)}")
        print(f"New: {len(new)}   Known/tolerated: {len(known)}")

    if args.check and new:
        print(f"\nFAILED: {len(new)} new layering violation(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
