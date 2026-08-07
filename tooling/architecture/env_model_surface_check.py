"""Gate the framework's *string-keyed* dependency on addon-owned models.

``core-does-not-depend-on-addons`` (``layer_check.py``) reasons about **import**
edges, so it is blind to the framework's largest real coupling to its own
consumer: core packages reach ~30 models that live in ``addons/base`` through
``env["res.users"]`` / ``self.env["ir.attachment"]`` string subscripts, which
compile to no import at all. The import gate reports two tolerated edges while
this whole surface passes unmeasured — the same class of blind spot
``mixin_coupling_check`` and ``env_surface_check`` were built to close for the
call graph and the ``env`` seam.

This checker inventories every ``env[<model literal>]`` (and ``self.env[...]``)
access in the framework packages and ratchets the **set of distinct models**
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

#: The framework's *acknowledged* model dependency surface. Ratcheted exact:
#: adding a model here without a reason, or leaving a stale one, both defeat the
#: point. Regenerate with ``--print-baseline`` after an intentional change.
KNOWN_MODEL_SURFACE: frozenset[str] = frozenset(
    {
        "base",
        "base.language.install",
        "decimal.precision",
        "ir.actions.server",
        "ir.attachment",
        "ir.config_parameter",
        "ir.default",
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

    @property
    def models(self) -> set[str]:
        return {r.model for r in self.reaches}

    @property
    def ok(self) -> bool:
        return not self.added and not self.removed


class _EnvModelCollector(ast.NodeVisitor):
    """Collect ``env["literal"]`` / ``<x>.env["literal"]`` subscripts."""

    def __init__(self) -> None:
        self.hits: list[tuple[str, int]] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.generic_visit(node)
        value = node.value
        is_env = (isinstance(value, ast.Attribute) and value.attr == "env") or (
            isinstance(value, ast.Name) and value.id == "env"
        )
        if not is_env:
            return
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            if _MODEL_RE.match(key.value):
                self.hits.append((key.value, node.lineno))


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
    lines.append("-" * 64)
    if report.ok:
        lines.append("Framework model surface matches the acknowledged set. ✓")
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
