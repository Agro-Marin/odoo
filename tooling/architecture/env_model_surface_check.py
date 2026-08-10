"""Gate the framework's *string-keyed* dependency on addon-owned models.

``core-does-not-depend-on-addons`` (``layer_check.py``) reasons about **import**
edges, so it is blind to the framework's largest real coupling to its own
consumer: core packages reach ~30 models that live in ``addons/base`` through
``env["res.users"]`` / ``self.env["ir.attachment"]`` string subscripts, which
compile to no import at all. The import gate reports two tolerated edges while
this whole surface passes unmeasured — the same class of blind spot
``mixin_coupling_check`` and ``env_surface_check`` were built to close for the
call graph and the ``env`` seam.

This checker inventories every model reach in the framework packages -- through
``env[...]``, the ``env`` accessors, ``registry[...]``/``pool[...]``,
``.get("...")``, ``in registry`` and relational comodel arguments, the six
syntaxes the framework actually uses (see ``_EnvModelCollector``) -- and
ratchets the **set of distinct models**
exact-mode, like the count ratchets: a *new* model dependency from core fails CI
(surfacing coupling that would otherwise creep in silently), and a model that is
no longer referenced also fails (so a genuine decoupling is committed, not
quietly reintroducible). ``addons/`` and test files are out of scope — an addon
depending on another model is ordinary; the framework doing so is the thing
worth watching.

It does not forbid the coupling — several of these models (``ir.model.data``,
``res.lang``, ``ir.config_parameter``) are framework-essential despite living in
an addon, which is itself the argument for eventually promoting their
*interfaces* into core (Protocols in ``odoo/``, implementations in ``base``),
exactly as the fork already did for ``MODULE_UNINSTALL_FLAG`` and the locale
number helpers. The gate makes the surface visible and bounded meanwhile.

Usage::

  python tooling/architecture/env_model_surface_check.py            # report
  python tooling/architecture/env_model_surface_check.py --check    # CI: exit 1 on drift
  python tooling/architecture/env_model_surface_check.py --json     # machine-readable
"""

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="env_model_surface_check")
CORE = REPO_ROOT / "odoo"

#: Framework packages scanned. Every package under ``odoo/`` is either here or
#: in :data:`SCOPE_EXEMPT_PACKAGES` with a reason, asserted by
#: ``test_every_core_package_is_scoped_or_exempt`` — the scope of a gate is a
#: hand-maintained list, and an unlisted package cannot fail it.
SCOPE_PACKAGES: tuple[str, ...] = (
    "orm",
    "http",
    "service",
    "modules",
    "db",
    "cli",
    "tools",
    "libs",
    # Added 2026-08 when the scope was first tested for completeness. The three
    # public shims held 0 model literals, and ``_monkeypatches`` 0; they are in
    # scope so that a *future* one is seen rather than silently unmeasured.
    "api",
    "fields",
    "models",
    "_monkeypatches",
    # ``tests`` (the shipped test *framework*) holds 12 literals reaching 5
    # models — res.users, ir.module.module, ir.attachment, ir.config_parameter,
    # ir.ui.view — every one of them ALREADY in KNOWN_MODEL_SURFACE, so bringing
    # it in scope changed the ratchet by nothing and only widened what is
    # watched. Note this deliberately diverges from ``layer_check``'s
    # ``CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT``, which excuses ``tests``:
    # there the question is whether the framework may *import* an addon, and a
    # test framework driving application code is the job. Here the question is
    # what the framework's string-keyed model surface *is*, and
    # ``module_operations.py`` driving ``ir.module.module`` is a real part of it.
    "tests",
)

#: Packages deliberately outside the scan, each with the reason it is out.
SCOPE_EXEMPT_PACKAGES: frozenset[str] = frozenset(
    {
        # An addon referencing another model is ordinary application coupling;
        # the framework reaching into an addon-owned model is the surface this
        # gate bounds. Scanning addons would measure the wrong thing entirely.
        "addons",
        # Dated one-shot source-rewrite scripts run by ``odoo-bin
        # upgrade_code``. They manipulate *source text* of other repos' addons,
        # so any model name in them is data being rewritten, not a dependency
        # this framework carries.
        "upgrade_code",
    }
)

#: A string literal is treated as a model name when it is dotted lowercase
#: (``res.users``, ``ir.model.data``) or the special root model ``base``.
_MODEL_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$|^base$")

#: ``Environment`` members that resolve to an addon-owned model, and to which.
#:
#: Without these this gate counts *namings*, not *reaches*, and the two come
#: apart. ``Environment`` wraps several model lookups in cached properties --
#: ``env.user`` is ``self["res.users"]``, ``env.company`` is
#: ``self["res.company"]``, and so on -- so every consumer of one reaches an
#: addon-owned model while producing no subscript for the collector to see.
#: Measured on 2026-08-08, that hid **35 core reaches** behind six names, and
#: made the metric reducible without reducing anything: moving an
#: ``env["res.users"]`` behind ``env.user`` lowered the count and left the
#: coupling identical.
#:
#: The seven ``SUBTREES_WITH_NO_MODEL_REACH`` were all clean of this channel when
#: it was closed, so this is a hole being shut before it is used rather than a
#: violation being recorded. ``test_the_accessor_map_covers_environment`` keeps
#: the map honest: every ``self["literal"]`` inside ``environment.py`` must be
#: reachable from some entry here, so a new accessor cannot be added without
#: extending this.
ENV_MODEL_ACCESSORS: dict[str, str] = {
    "user": "res.users",
    "company": "res.company",
    "companies": "res.company",
    "lang": "res.lang",
    "_lang": "res.lang",
    "_ir_defaults": "ir.default",
}

#: Models ``environment.py`` consults internally without handing one to a caller.
#:
#: The distinction that decides whether a member belongs here or in
#: :data:`ENV_MODEL_ACCESSORS` is whether it *returns a recordset of that model*.
#: ``env.user`` does, so its consumers reach ``res.users`` and are counted.
#: ``env.ref("module.xmlid")`` does not: it asks ``ir.model.data`` to resolve the
#: xmlid and then returns ``self[res_model].browse(res_id)`` -- a record of some
#: *other* model, chosen at run time. Counting every ``env.ref`` call site as an
#: ``ir.model.data`` reach would say the framework is coupled to that model in
#: ~100 places when it is coupled in one, here.
ENV_INTERNAL_MODEL_LOOKUPS: frozenset[str] = frozenset({"ir.model.data"})

#: Subtrees that must reach **no** addon-owned model at all.
#:
#: ``KNOWN_MODEL_SURFACE`` below ratchets *which* models the framework reaches;
#: it cannot express *who* reaches them, because it is one flat set for the whole
#: scope. That gap is demonstrable, not theoretical: appending
#: ``env["ir.model"].search([])`` to ``odoo/orm/components/model_graph.py`` -- a
#: package whose whole contract is that it is pure Python -- passes this gate
#: (``ir.model`` is already in the set, so nothing is *added*), and also passes
#: ``layer_check`` (a subscript is not an import), ``env_surface_check`` and
#: ``pool_surface_check``. All four green, on the one package that is supposed to
#: be free of the ORM entirely.
#:
#: These seven are pinned at zero because each already claims the property for an
#: independent reason, so a first reach is a contradiction rather than a cost:
#:
#:   orm/components   `orm-components-are-pure-python`; no odoo import at all
#:   libs             the dependency-free layer (`libs-is-dependency-free`)
#:   db               `db-is-orm-agnostic`; talks to the ORM only via injection
#:   api/fields/models  thin re-export shims -- a facade that reaches a model is
#:                      no longer a facade
#:   _monkeypatches   third-party patching, applied before a registry exists
#:
#: Measured at zero when this landed. Deliberately *not* the full (package,
#: model) cross-product: that would be ~54 pairs and would fire on every ordinary
#: new reach inside a package that already reaches models, which is noise. The
#: invariant worth gating is the categorical one -- these subtrees reach nothing.
SUBTREES_WITH_NO_MODEL_REACH: tuple[str, ...] = (
    "odoo/orm/components",
    "odoo/libs",
    "odoo/db",
    "odoo/api",
    "odoo/fields",
    "odoo/models",
    "odoo/_monkeypatches",
)

#: The framework's *acknowledged* model dependency surface. Ratcheted exact:
#: adding a model here without a reason, or leaving a stale one, both defeat the
#: point. Regenerate with ``--print-baseline`` after an intentional change.
#:
#: ``ir.demo_failure`` and ``res.partner`` joined on 2026-08-09, when the
#: collector learned the four channels below the original two. Neither is new
#: coupling -- both predate the gate and were simply spelled in a syntax it did
#: not read: ``env.get("ir.demo_failure")`` in ``modules/loading.py`` (recording
#: a demo-data failure, optional by construction) and
#: ``if "res.partner" in registry:`` in ``orm/model_test_env.py`` (injecting a
#: fixture row when the model happens to be loaded). They are acknowledged here
#: rather than removed because both are deliberate optional-model probes.
KNOWN_MODEL_SURFACE: frozenset[str] = frozenset(
    {
        "base",
        "base.language.install",
        "decimal.precision",
        "ir.actions.server",
        "ir.attachment",
        "ir.config_parameter",
        "ir.default",
        "ir.demo_failure",
        "ir.fields.converter",
        "ir.http",
        "ir.model",
        "ir.model.access",
        "ir.model.constraint",
        "ir.model.data",
        "ir.model.fields",
        "ir.model.fields.selection",
        "ir.model.inherit",
        "ir.model.relation",
        "ir.module.module",
        "ir.qweb",
        "ir.rule",
        "ir.ui.menu",
        "ir.ui.view",
        "res.company",
        "res.country",
        "res.currency.rate",
        "res.device.log",
        "res.groups",
        "res.lang",
        "res.partner",
        "res.users",
    }
)


@dataclass(frozen=True)
class Reach:
    """One ``env[model]`` access site."""

    model: str
    path: str  # repo-relative
    lineno: int


@dataclass
class Report:
    reaches: list[Reach] = field(default_factory=list)
    #: models referenced now but absent from the baseline (new coupling)
    added: set[str] = field(default_factory=set)
    #: models in the baseline no longer referenced (locked-in decoupling)
    removed: set[str] = field(default_factory=set)
    #: reaches from a subtree that must reach nothing (see
    #: :data:`SUBTREES_WITH_NO_MODEL_REACH`). Separate from ``added`` because the
    #: model itself may be perfectly well known -- it is the *reacher* that is
    #: the violation, which the flat model set cannot express.
    forbidden: list[Reach] = field(default_factory=list)

    @property
    def models(self) -> set[str]:
        return {r.model for r in self.reaches}

    @property
    def ok(self) -> bool:
        return not self.added and not self.removed and not self.forbidden


def _is_env_expression(node: ast.expr) -> bool:
    """Whether ``node`` evaluates to an ``Environment`` -- ``env`` or ``x.env``."""
    return (isinstance(node, ast.Attribute) and node.attr == "env") or (
        isinstance(node, ast.Name) and node.id == "env"
    )


#: Names that evaluate to a :class:`Registry`. ``Registry.__getitem__`` hands
#: back the model *class* -- the same coupling as ``env[...]``, spelled one
#: attribute over -- and ``pool`` is the ORM's own alias for it.
_REGISTRY_NAMES = frozenset({"registry", "pool"})


def _is_registry_expression(node: ast.expr) -> bool:
    """Whether ``node`` evaluates to a ``Registry`` -- ``registry``/``pool``."""
    return (isinstance(node, ast.Attribute) and node.attr in _REGISTRY_NAMES) or (
        isinstance(node, ast.Name) and node.id in _REGISTRY_NAMES
    )


def _is_model_container(node: ast.expr) -> bool:
    """Whether ``node`` is something a model name can be looked up in."""
    return _is_env_expression(node) or _is_registry_expression(node)


#: Relational field constructors whose FIRST positional argument is a comodel
#: name. ``metaclass.py`` builds the ``create_uid``/``write_uid`` magic fields
#: as ``Many2one("res.users", ...)``, which is a reach on an addon-owned model
#: with no subscript anywhere.
_COMODEL_CONSTRUCTORS = frozenset({"Many2one", "One2many", "Many2many"})


class _EnvModelCollector(ast.NodeVisitor):
    """Collect model reaches, by every syntax the framework uses to spell one.

    Six channels. The first two were the original pair; the other four were
    added 2026-08-09, after measuring that they carried **31% of all model
    reaches in the core** while this gate reported on the rest. Two of the
    models they reach (``ir.demo_failure``, ``res.partner``) were absent from
    :data:`KNOWN_MODEL_SURFACE` -- a set whose entire purpose is to be closed.

    * ``env["literal"]`` / ``<x>.env["literal"]`` -- naming a model outright;
    * ``env.<accessor>`` for the members in :data:`ENV_MODEL_ACCESSORS` --
      reaching one without naming it;
    * ``registry["literal"]`` / ``pool["literal"]`` -- ``Registry.__getitem__``
      returns the model *class*, the same coupling one attribute over;
    * ``env.get("literal")`` / ``registry.get("literal")`` -- ``Mapping.get``,
      not ``__getitem__``, so no ``Subscript`` node exists to see;
    * ``"literal" in registry`` / ``in env`` -- a membership test still names
      the model, and is how optional models are probed;
    * ``Many2one("literal", ...)`` and the other relational constructors --
      a comodel in argument position, which is how ``metaclass.py`` names
      ``res.users`` for the ``create_uid``/``write_uid`` magic fields.

    Still NOT covered, deliberately: a model name sitting in a plain data
    structure or passed as a SQL parameter. Catching those needs the set of
    declared model names as a corpus rather than a syntactic rule, since
    ``_MODEL_RE`` alone matches any dotted lowercase string. Where they exist
    they are being removed at the source instead.
    """

    def __init__(self) -> None:
        self.hits: list[tuple[str, int]] = []

    def _add_if_model(self, key: ast.expr, lineno: int) -> None:
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and _MODEL_RE.match(key.value)
        ):
            self.hits.append((key.value, lineno))

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.generic_visit(node)
        if _is_model_container(node.value):
            self._add_if_model(node.slice, node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.generic_visit(node)
        model = ENV_MODEL_ACCESSORS.get(node.attr)
        if model is not None and _is_env_expression(node.value):
            self.hits.append((model, node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        if not node.args:
            return
        func = node.func
        is_container_get = (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and _is_model_container(func.value)
        )
        is_comodel_arg = isinstance(func, ast.Name) and func.id in _COMODEL_CONSTRUCTORS
        if is_container_get or is_comodel_arg:
            self._add_if_model(node.args[0], node.lineno)

    def visit_Compare(self, node: ast.Compare) -> None:
        self.generic_visit(node)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.In | ast.NotIn) and _is_model_container(comparator):
                self._add_if_model(node.left, node.lineno)


def iter_scope_files() -> list[Path]:
    out: list[Path] = []
    for pkg in SCOPE_PACKAGES:
        base = CORE / pkg
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            parts = p.parts
            if "tests" in parts or "__pycache__" in parts or p.name.startswith("test_"):
                continue
            out.append(p)
    return out


def check(files: list[Path] | None = None) -> Report:
    report = Report()
    for path in files if files is not None else iter_scope_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        collector = _EnvModelCollector()
        collector.visit(tree)
        rel = path.relative_to(REPO_ROOT).as_posix()
        for model, lineno in collector.hits:
            report.reaches.append(Reach(model, rel, lineno))
    report.added = report.models - KNOWN_MODEL_SURFACE
    report.removed = KNOWN_MODEL_SURFACE - report.models
    report.forbidden = [
        r
        for r in report.reaches
        if r.path.startswith(tuple(f"{s}/" for s in SUBTREES_WITH_NO_MODEL_REACH))
    ]
    return report


def _render(report: Report) -> str:
    lines = ["Framework → addon-model surface (string-keyed env access)", "=" * 64]
    by_model: dict[str, set[str]] = {}
    for r in report.reaches:
        by_model.setdefault(r.model, set()).add(r.path)
    lines.append(f"distinct models reached: {len(by_model)}")
    lines.append(f"total access sites: {len(report.reaches)}")
    lines.append("")
    for model in sorted(by_model):
        marker = "  NEW" if model in report.added else ""
        lines.append(f"  {model}  ({len(by_model[model])} files){marker}")
    if report.added:
        lines.append("")
        lines.append("NEW model dependencies (not in the acknowledged surface):")
        for m in sorted(report.added):
            lines.append(f"  + {m}")
            sites = [f"{r.path}:{r.lineno}" for r in report.reaches if r.model == m]
            lines.extend(f"      {s}" for s in sites[:5])
    if report.removed:
        lines.append("")
        lines.append(
            "Models in the baseline no longer referenced (commit the removal):"
        )
        lines.extend(f"  - {m}" for m in sorted(report.removed))
    if report.forbidden:
        lines.append("")
        lines.append(
            "Subtrees that must reach NO model, but do "
            "(the model may be known -- the reacher is the violation):"
        )
        lines.extend(
            f"  ! {r.path}:{r.lineno}  env[{r.model!r}]" for r in report.forbidden
        )
    lines.append("-" * 64)
    if report.ok:
        lines.append("Framework model surface matches the acknowledged set. ✓")
    elif report.forbidden and not (report.added or report.removed):
        lines.append("FAILED: a subtree pinned at zero model reaches now reaches one.")
    else:
        lines.append("FAILED: framework model surface drifted from the baseline.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate the framework's string-keyed dependency on addon models."
    )
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--print-baseline",
        action="store_true",
        help="print the current model set as a Python literal (to update the baseline)",
    )
    args = parser.parse_args(argv)

    report = check()

    if args.print_baseline:
        for m in sorted(report.models):
            print(f'        "{m}",')
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "models": sorted(report.models),
                    "added": sorted(report.added),
                    "removed": sorted(report.removed),
                    "sites": len(report.reaches),
                    "ok": report.ok,
                },
                indent=2,
            )
        )
    else:
        print(_render(report))

    if args.check and not report.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
