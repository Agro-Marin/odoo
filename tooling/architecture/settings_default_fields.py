"""A settings ``default_<name>`` field must name a field its ``default_model`` declares.

``res.config.settings.set_values`` stores such a field through
``ir.default.set(default_model, name)``, which raises ``Invalid field`` when the
model has no field of that name. The settings view still renders, so nothing
fails until someone saves Settings: a rename of the model field that misses the
settings declaration breaks every save in every database with the module
installed, and a data file that calls ``execute`` breaks installing any module
installed beside it. ``l10n_be_hr_payroll`` renamed ``hr.version.mobile`` to
``mobile_subscription`` and kept ``default_mobile``; marin could no longer be
installed next to Belgian payroll.

The scan merges every declaration of a model across the checkout and the sibling
repos, follows ``_inherit`` parents and ``_inherits`` delegations, and counts the
magic fields every model has.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import (
    find_odoo_root,
    find_workspace,
    in_full_workspace,
    sibling_repo_paths,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache
from _sources import display_across_repos, iter_files

ROOT = find_odoo_root(Path(__file__).resolve(), tool="settings_default_fields")

CHECKOUT_ROOTS = ("addons", "odoo/addons")
SKIPPED_DIRS = frozenset({"tests", "migrations", "upgrades", "static"})
MAGIC_FIELDS = frozenset(
    {"id", "display_name", "create_uid", "create_date", "write_uid", "write_date"}
)
SETTINGS_MODEL = "res.config.settings"
PREFIX = "default_"


class NoSource(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Offender:
    path: str
    line: int
    settings_field: str
    default_model: str

    @property
    def target(self) -> str:
        return f"{self.default_model}.{self.settings_field.removeprefix(PREFIX)}"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.settings_field} -> {self.target}"


def _string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _assigned(cls: ast.ClassDef, name: str) -> ast.AST | None:
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == name
        ):
            return stmt.value
    return None


def _inherit(cls: ast.ClassDef) -> list[str]:
    node = _assigned(cls, "_inherit")
    if (single := _string(node)) is not None:
        return [single]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [name for name in map(_string, node.elts) if name]
    return []


def _delegations(cls: ast.ClassDef) -> dict[str, str]:
    node = _assigned(cls, "_inherits")
    if not isinstance(node, ast.Dict):
        return {}
    pairs = zip(map(_string, node.keys), map(_string, node.values), strict=True)
    return {model: field for model, field in pairs if model and field}


def _field_calls(cls: ast.ClassDef):
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
        elif isinstance(stmt, ast.AnnAssign):
            target = stmt.target
        else:
            continue
        call = stmt.value
        if (
            isinstance(target, ast.Name)
            and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "fields"
        ):
            yield stmt.lineno, target.id, call


def default_roots() -> list[Path]:
    roots = [ROOT / rel for rel in CHECKOUT_ROOTS]
    if find_workspace(ROOT) is not None:
        roots += sibling_repo_paths(ROOT)
    return roots


def _sources(roots: list[Path]) -> list[Path]:
    paths = []
    for root in roots:
        for path in iter_files(root, "*.py"):
            parts = path.relative_to(root).parts
            if SKIPPED_DIRS.intersection(parts[:-1]) or path.name.startswith("test_"):
                continue
            paths.append(path)
    return sorted(paths)


def measure(
    roots: list[Path] | None = None, *, full_workspace: bool = False
) -> list[Offender]:
    roots = [root for root in (roots or default_roots()) if root.is_dir()]
    paths = _sources(roots)
    if not paths:
        raise NoSource(
            "no Python source under " + ", ".join(map(str, roots or ["(no roots)"]))
        )
    declared: defaultdict[str, set[str]] = defaultdict(set)
    parents: defaultdict[str, set[str]] = defaultdict(set)
    settings: dict[str, dict[str, ast.AST]] = {}
    settings_at: dict[str, tuple[str, int]] = {}
    for path in paths:
        rel = display_across_repos(path, ROOT)
        for cls in ast.walk(_ast_cache.parse_file(path)):
            if not isinstance(cls, ast.ClassDef):
                continue
            inherit = _inherit(cls)
            name = _string(_assigned(cls, "_name"))
            for model in [name] if name else inherit:
                parents[model].update(parent for parent in inherit if parent != model)
                for parent, link in _delegations(cls).items():
                    parents[model].add(parent)
                    declared[model].add(link)
                for line, field, call in _field_calls(cls):
                    declared[model].add(field)
                    if model == SETTINGS_MODEL and field.startswith(PREFIX):
                        keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
                        settings.setdefault(field, {}).update(keywords)
                        if "default_model" in keywords or field not in settings_at:
                            settings_at[field] = (rel, line)

    def fields_of(model: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if model in seen:
            return set()
        found = set(declared[model])
        for parent in parents[model]:
            found |= fields_of(parent, seen | {model})
        return found

    offenders = []
    for field, keywords in sorted(settings.items()):
        default_model = _string(keywords.get("default_model"))
        if default_model is None:
            continue
        if default_model not in declared and not full_workspace:
            continue
        if field.removeprefix(PREFIX) not in fields_of(default_model) | MAGIC_FIELDS:
            path, line = settings_at[field]
            offenders.append(Offender(path, line, field, default_model))
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="a settings default_<name> field whose default_model has no <name>"
    )
    parser.add_argument("--check", action="store_true", help="fail on any offender")
    parser.add_argument("--count", action="store_true", help="print the offender count")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("roots", nargs="*", type=Path)
    args = parser.parse_args(argv)
    try:
        offenders = measure(
            args.roots or None,
            full_workspace=not args.roots and in_full_workspace(ROOT),
        )
    except NoSource as error:
        print(f"settings_default_fields: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([asdict(offender) for offender in offenders], indent=2))
    elif args.count:
        print(len(offenders))
    else:
        for offender in offenders:
            print(f"MISSING  {offender}")
        print(
            f"{len(offenders)} settings default fields name a field their model lacks"
        )
    if args.check:
        return 1 if offenders else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
