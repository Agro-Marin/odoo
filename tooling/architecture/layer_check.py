#!/usr/bin/env python3


from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0005"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="layer_check")
PKG_ROOT = ROOT / "odoo"


UNRECORDED = "unrecorded"


@dataclass(frozen=True)
class Contract:
    name: str
    source: tuple[str, ...]
    forbidden: tuple[str, ...]
    allow: tuple[str, ...]
    rationale: str
    adr: str
    allow_exact: tuple[str, ...] = ()
    source_exact: tuple[str, ...] = ()
    # True when the contract bounds *import-time* cost rather than use: an
    # import inside a function body creates no load-time edge and is the
    # sanctioned way to satisfy such a contract.
    module_scope_only: bool = False


@dataclass(frozen=True)
class Known:
    module: str
    imports: str
    reason: str


CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT = frozenset(
    {
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


CONTRACTS: tuple[Contract, ...] = (
    Contract(
        name="libs-is-dependency-free",
        adr="0004",
        source=("odoo.libs",),
        forbidden=("odoo",),
        allow=("odoo.libs",),
        rationale=(
            "odoo/libs/ imports no odoo.* except odoo.libs, so it stays reusable and "
            "testable in isolation. Third-party packages and odoo_rust are allowed; "
            "read the name as libs-is-odoo-free. See ADR-0004."
        ),
    ),
    Contract(
        name="db-is-orm-agnostic",
        adr="0003",
        source=("odoo.db",),
        forbidden=("odoo.orm", "odoo.models", "odoo.fields", "odoo.api"),
        allow=("odoo.libs",),
        rationale=(
            "db/ reaches the ORM only through injected hooks "
            "(BaseCursor._flushing_savepoint_cls), never by importing it."
        ),
    ),
    Contract(
        name="tools-stays-below-the-serving-tier",
        adr="0075",
        source=("odoo.tools",),
        forbidden=("odoo.http",),
        allow=(),
        module_scope_only=True,
        rationale=(
            "odoo.http imports odoo.tools in eight modules, so a module-scope "
            "import back the other way makes `import odoo.tools.<anything>` load "
            "the whole serving tier.  urls.py did exactly that for `request`, and "
            "ir_qweb plus ~60 payment/delivery/l10n modules import from it, most "
            "only for urljoin.  A helper that genuinely needs the request imports "
            "it inside the function, the way cache_version.py already does."
        ),
    ),
    Contract(
        name="tools-does-not-reach-the-orm-runtime",
        adr=UNRECORDED,
        source=("odoo.tools",),
        forbidden=("odoo.orm.runtime",),
        allow=(),
        rationale=(
            "Utilities may use ORM values and types but must not reach the runtime. "
            "Every layer contract is a direct-edge rule, so odoo/orm/fields -> "
            "odoo.tools.x -> odoo.orm.runtime needs its own rule; the tools/ "
            "references that exist are TYPE_CHECKING-guarded."
        ),
    ),
    Contract(
        name="orm-helpers-and-registration-stay-below-runtime",
        adr=UNRECORDED,
        source=("odoo.orm.helpers", "odoo.orm.registration"),
        forbidden=("odoo.orm.runtime",),
        allow=(),
        rationale=(
            "orm/helpers.py and orm/registration.py are reachable from Layer 2 without "
            "Layer 2 importing them, so they are pinned below the runtime. "
            "model_test_env.py is deliberately not a source: the DB-free harness "
            "constructs Environment/Transaction/Registry by design."
        ),
    ),
    Contract(
        name="orm-components-are-pure-python",
        adr="0002",
        source=("odoo.orm.components",),
        forbidden=("odoo",),
        allow=("odoo.orm.components", "odoo.libs"),
        rationale=(
            "FieldCache / ComputeEngine / UnitOfWork / ModelGraph take their "
            "collaborators by injection and must be testable without an Environment, "
            "Registry, or database."
        ),
    ),
    Contract(
        name="orm-layer1-below-models-and-runtime",
        adr="0001",
        source=("odoo.orm.fields", "odoo.orm.domain"),
        forbidden=("odoo.orm.models", "odoo.orm.runtime", "odoo.models", "odoo.api"),
        allow=(),
        rationale=(
            "Fields and domains (Layer 1) sit below models (Layer 2) and runtime "
            "(Layer 3); crossing that at runtime reintroduces the import cycles the "
            "layering prevents."
        ),
    ),
    Contract(
        name="orm-layer0-is-foundational",
        adr="0001",
        source=(
            "odoo.orm.primitives",
            "odoo.orm.parsing",
            "odoo.orm.validation",
            "odoo.orm.constants",
            "odoo.orm._typing",
            "odoo.orm._protocols",
        ),
        forbidden=(
            "odoo.orm.fields",
            "odoo.orm.domain",
            "odoo.orm.models",
            "odoo.orm.runtime",
            "odoo.orm.components",
            "odoo.fields",
            "odoo.models",
            "odoo.api",
        ),
        allow=(),
        rationale=(
            "Layer 0 (primitives, parsing, validation, constants, _typing, _protocols) "
            "may import no higher ORM layer, nor the odoo.fields / odoo.models / "
            "odoo.api shims. _protocols is typing-only at runtime, which is why its "
            "reach for orm.domain is TYPE_CHECKING-guarded."
        ),
    ),
    Contract(
        name="transaction-primitive-is-transport-agnostic",
        adr="0003",
        source=("odoo.service.transaction",),
        forbidden=("odoo.http",),
        allow=(),
        rationale=(
            "retrying() is a transaction primitive and must not reach odoo.http. The "
            "transport injects a RetryParticipant, the shape ADR-0003 uses to give db/ "
            "its flushing savepoint."
        ),
    ),
    Contract(
        name="root-modules-are-foundational",
        adr="0016",
        source=("odoo.exceptions", "odoo.release"),
        forbidden=("odoo",),
        allow=("odoo.libs",),
        rationale=(
            "odoo/exceptions.py and odoo/release.py are imported by everything and may "
            "import no odoo package except odoo.libs, which is itself dependency-free. "
            "Not odoo/logutils.py: it imports odoo.db, odoo.release and odoo.tools and "
            "is a consumer of the stack."
        ),
    ),
    Contract(
        name="orm-models-below-runtime",
        adr="0001",
        source=("odoo.orm.models",),
        forbidden=("odoo.orm.runtime",),
        allow=(),
        rationale=(
            "Models (Layer 2) sit below the runtime (Layer 3: Environment, Registry, "
            "Transaction). Layer 3 builds on Layer 2, not the reverse."
        ),
    ),
    Contract(
        name="core-does-not-depend-on-addons",
        adr=UNRECORDED,
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
            "odoo.init",
            "odoo.logutils",
            "odoo.exceptions",
            "odoo.release",
            "odoo._testing_bootstrap",
            "odoo.__main__",
        ),
        source_exact=("odoo",),
        forbidden=("odoo.addons",),
        allow=(),
        allow_exact=("odoo.addons", "odoo.addons.__path__"),
        rationale=(
            "The framework core must be importable without any addon. Reach addon "
            "behaviour through the registry (env['ir.cron']) or move the shared "
            "definition down into the core. Bare `import odoo.addons` for __path__ "
            "discovery is not matched here."
        ),
    ),
    Contract(
        name="facade-boundary",
        adr="0008",
        source=("odoo.addons", "addons"),
        forbidden=("odoo.orm",),
        allow=(),
        rationale=(
            "Addon and application code imports model features from the public facades "
            "(odoo.api, odoo.fields, odoo.models), never from odoo.orm.* internals, so "
            "the ORM stays free to evolve behind a stable surface."
        ),
    ),
    Contract(
        name="orm-seams-stay-below-models-and-runtime",
        adr="0001",
        source=("odoo.orm._recordset", "odoo.orm.decorators"),
        forbidden=("odoo.orm.models", "odoo.orm.runtime", "odoo.models", "odoo.api"),
        allow=(),
        rationale=(
            "The Layer-1 recordset injection seam (orm/_recordset.py) and the @api "
            "decorators must not import the model or runtime layers at runtime; the "
            "seam exists to break that cycle."
        ),
    ),
    Contract(
        name="db-resilience-below-connectivity",
        adr=UNRECORDED,
        source=(
            "odoo.db.breaker",
            "odoo.db.lag",
            "odoo.db.budget",
            "odoo.db.leaks",
            "odoo.db.reaper",
            "odoo.db.probe",
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
            "odoo.db.endpoints",
        ),
        allow=(),
        rationale=(
            "Connectivity owns connections and calls into resilience (breaker, lag, "
            "budget, leaks, reaper, probe, metrics, stats), never the reverse, so "
            "resilience stays testable without a pool or a cursor. Shared leaf "
            "helpers belong in [foundation], which both may import. `probe` is "
            "resilience because it answers 'is this DSN reachable' from `dsn` alone; "
            "`endpoints` is connectivity because it builds pools."
        ),
    ),
    Contract(
        name="http-features-below-serving",
        adr=UNRECORDED,
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
            "odoo.http._retry",
        ),
        allow=(),
        rationale=(
            "The [features] modules describe or decorate the request pipeline; the "
            "[serving] modules run it. Features must not import serving."
        ),
    ),
    Contract(
        name="orm-below-the-serving-tier",
        adr=UNRECORDED,
        source=("odoo.orm",),
        forbidden=("odoo.service", "odoo.http", "odoo.cli"),
        allow=(),
        rationale=(
            "service/, http/ and cli/ import the ORM freely; the reverse direction "
            "stays empty so a Registry/Environment can exist and be tested without a "
            "server. Constants both tiers need belong in odoo.db or odoo.tools, below "
            "both."
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
    module: str
    is_init: bool = False
    found: list[tuple[str, int]] = field(default_factory=list)
    deferred: set[int] = field(default_factory=set)
    _depth: int = 0

    def _enter_function(self, node: ast.AST) -> None:
        # Imports below a def cost nothing until the function is called, so they
        # create no load-time edge.  Contracts that exist to bound import cost
        # (module_scope_only) skip them; contracts about what a layer may *use*
        # still see them.
        self._depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_function(node)

    def _record(self, name: str, lineno: int) -> None:
        self.found.append((name, lineno))
        if self._depth:
            self.deferred.add(lineno)

    def _resolve_relative(self, node_module: str | None, level: int) -> str:
        base = self.module if self.is_init else self.module.rsplit(".", 1)[0]
        for _ in range(level - 1):
            base = base.rsplit(".", 1)[0] if "." in base else ""
        if node_module:
            return f"{base}.{node_module}" if base else node_module
        return base

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            base = self._resolve_relative(node.module, node.level)
        else:
            base = node.module or ""
        if base:
            self._record(base, node.lineno)
            for alias in node.names:
                if alias.name != "*":
                    self._record(f"{base}.{alias.name}", node.lineno)

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_test(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
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
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _matches(dotted: str, prefixes: tuple[str, ...]) -> bool:
    return any(dotted == p or dotted.startswith(p + ".") for p in prefixes)


_CORE_TEST_FRAMEWORK_PACKAGE = ("odoo", "tests")


def _is_test_file(path: Path) -> bool:
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        parts = path.parts
    if parts[: len(_CORE_TEST_FRAMEWORK_PACKAGE)] == _CORE_TEST_FRAMEWORK_PACKAGE:
        return path.name.startswith("test_") or path.name == "conftest.py"
    return (
        "tests" in parts or path.name == "conftest.py" or path.name.startswith("test_")
    )


def _collapse_nested(roots: list[Path]) -> list[Path]:

    dirs = [r for r in roots if r.is_dir()]
    return [r for r in roots if not any(d != r and d in r.parents for d in dirs)]


def _source_exact_files() -> list[Path]:

    files: list[Path] = []
    for contract in CONTRACTS:
        for dotted in contract.source_exact:
            base = ROOT.joinpath(*dotted.split("."))
            for candidate in (base / "__init__.py", base.with_suffix(".py")):
                if candidate.is_file():
                    files.append(candidate)
                    break
    return files


def iter_source_files() -> list[Path]:
    source_prefixes = {p for c in CONTRACTS for p in c.source}
    roots = _collapse_nested(
        sorted({ROOT.joinpath(*p.split(".")) for p in source_prefixes})
    )
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
        elif root.with_suffix(".py").is_file():
            files.append(root.with_suffix(".py"))
    files.extend(_source_exact_files())
    kept = [f for f in files if "__pycache__" not in f.parts and not _is_test_file(f)]
    return sorted(dict.fromkeys(kept))


def _is_known(module: str, target: str) -> bool:
    return any(
        _matches(module, (k.module,)) and _matches(target, (k.imports,))
        for k in KNOWN_VIOLATIONS
    )


def violations_for(
    module: str,
    imports: list[tuple[str, int]],
    path: str,
    deferred: set[int] | None = None,
) -> list[Violation]:
    deferred = deferred or set()

    found: list[Violation] = []
    for contract in CONTRACTS:
        if not (_matches(module, contract.source) or module in contract.source_exact):
            continue
        reported: set[tuple[int, str]] = set()
        for target, lineno in imports:
            if not _matches(target, contract.forbidden):
                continue
            if contract.module_scope_only and lineno in deferred:
                continue
            if _matches(target, contract.allow):
                continue
            if target in contract.allow_exact:
                continue
            if _matches(target, contract.source):
                continue
            if any(
                line == lineno and target.startswith(seen + ".")
                for line, seen in reported
            ):
                continue
            reported.add((lineno, target))
            found.append(
                Violation(
                    contract=contract.name,
                    module=module,
                    imports=target,
                    path=path,
                    lineno=lineno,
                )
            )
    return found


def check(files: list[Path] | None = None) -> tuple[list[Violation], list[Violation]]:

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
        for v in violations_for(
            module,
            collector.found,
            str(path.relative_to(ROOT)),
            collector.deferred,
        ):
            (known if _is_known(v.module, v.imports) else new).append(v)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW violation"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    scanned = len(files)
    if not scanned:
        parser.error("no Python sources found — the scan reached nothing")

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
