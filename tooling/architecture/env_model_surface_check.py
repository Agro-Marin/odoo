import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0029"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="env_model_surface_check")
CORE = REPO_ROOT / "odoo"

SCOPE_PACKAGES: tuple[str, ...] = (
    "orm",
    "http",
    "service",
    "modules",
    "db",
    "cli",
    "tools",
    "libs",
    "api",
    "fields",
    "models",
    "_monkeypatches",
    "tests",
)

SCOPE_EXEMPT_PACKAGES: frozenset[str] = frozenset(
    {
        "addons",
        "upgrade_code",
    }
)

_MODEL_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$|^base$")

ENV_MODEL_ACCESSORS: dict[str, str] = {
    "user": "res.users",
    "company": "res.company",
    "companies": "res.company",
    "lang": "res.lang",
    "_lang": "res.lang",
    "_ir_defaults": "ir.default",
}

ENV_INTERNAL_MODEL_LOOKUPS: frozenset[str] = frozenset({"ir.model.data"})

SUBTREES_WITH_NO_MODEL_REACH: tuple[str, ...] = (
    "odoo/orm/components",
    "odoo/libs",
    "odoo/db",
    "odoo/api",
    "odoo/fields",
    "odoo/models",
    "odoo/_monkeypatches",
)

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
    model: str
    path: str
    lineno: int


@dataclass
class Report:
    reaches: list[Reach] = field(default_factory=list)
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    forbidden: list[Reach] = field(default_factory=list)

    @property
    def models(self) -> set[str]:
        return {r.model for r in self.reaches}

    @property
    def ok(self) -> bool:
        return not self.added and not self.removed and not self.forbidden


def _is_env_expression(node: ast.expr) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "env") or (
        isinstance(node, ast.Name) and node.id == "env"
    )


_REGISTRY_NAMES = frozenset({"registry", "pool"})


def _is_registry_expression(node: ast.expr) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr in _REGISTRY_NAMES) or (
        isinstance(node, ast.Name) and node.id in _REGISTRY_NAMES
    )


def _is_model_container(node: ast.expr) -> bool:
    return _is_env_expression(node) or _is_registry_expression(node)


_COMODEL_CONSTRUCTORS = frozenset({"Many2one", "One2many", "Many2many"})


class _EnvModelCollector(ast.NodeVisitor):
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
