from __future__ import annotations

import argparse
import ast
import json
import sys
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

ROOT = find_odoo_root(Path(__file__).resolve(), tool="computed_default")

CHECKOUT_ROOTS = ("addons", "odoo/addons")
SKIPPED_DIRS = frozenset({"tests", "migrations", "upgrades", "static"})

REVIEWED: dict[str, str] = {
    "account.payment.state": "the compute starts from the stored state and only moves it forward; every payment starts in draft",
    "account.analytic.line.user_id": "probed: a timesheet created for another user's employee stores that employee's user",
    "appointment.question.is_reusable": "the compute only ever sets True, the default",
    "appointment.slot.end_hour": "create derives end_hour from start_hour and the appointment duration before defaults apply (AppointmentSlot.create)",
    "appointment.type.staff_user_ids": "probed: a resource-based type is created with no staff with or without the default; user-based types keep the creator as staff",
    "calendar.event.stop": "create derives stop from start and duration before defaults apply (_create_prepare_stop)",
    "delivery.carrier.country_id": "the compute keeps a country already set",
    "event.event.kanban_state": "the compute resets to normal unless cancelled; normal is where every event starts",
    "hr.expense.currency_id": "for a draft expense the default and the compute both give the company currency",
    "hr.leave.accrual.level.carryover_options": "the compute only ever sets unlimited, the default",
    "hr.leave.accrual.level.first_month_day": "the compute clamps the current day to its month; the default is a day it keeps",
    "hr.leave.accrual.level.second_month_day": "the compute clamps the current day to its month; the default is a day it keeps",
    "hr.leave.accrual.level.yearly_day": "the compute clamps the current day to its month; the default is a day it keeps",
    "hr.leave.accrual.level.frequency": "the compute only rewrites worked_hours",
    "hr.leave.accrual.level.milestone_date": "the compute only ever sets creation, the default",
    "hr.leave.accrual.plan.carryover_day": "the compute clamps the current day to its month",
    "hr.leave.accrual.level.maximum_leave": "the compute only ever writes 0, the default",
    "hr.leave.allocation.holiday_status_id": "the compute keeps a leave type already set",
    "hr.leave.allocation.number_of_days": "the compute reads number_of_days_display and number_of_hours_display, both computed from number_of_days, so a create can only name the field itself",
    "hr.work.entry.regeneration.wizard.date_to": "the default is the date_end the opening action passes in context, falsy without one",
    "loyalty.program.applies_on": "deliberate: _with_program_type_values documents that filling it on create broke the pos_loyalty tour",
    "mailing.mailing.mailing_model_id": "marketing_card's create derives it from the card campaign before defaults apply",
    "product.template.expense_policy": "every compute override only ever writes no, the default",
    "product.template.is_storable": "the compute only ever clears it on a product that is not goods; False, the default, is what it leaves on a create that names neither",
    "product.template.purchase_ok": "the compute only ever sets True, the default",
    "product.template.service_tracking": "every compute override only ever writes no, the default",
    "product.template.tracking": "the compute only ever writes none, the default",
    "project.project.allow_timesheets": "the compute skips records that have no _origin, so a new project keeps the default",
    "project.project.billing_type": "the compute only resets manually",
    "project.project.last_update_status": "a new project has no update, and the compute yields the default for that",
    "project.share.collaborator.wizard.send_invitation": "the compute only ever sets True, the default",
    "project.task.ai_support_state": "the compute defers to the stored state, and a new task has none",
    "project.task.company_id": "the default is the context project's company, what the compute yields; without that context it is falsy and skipped",
    "project.task.step_id": "the default is the context project's first step, and _update_create_vals writes step_id for every task with a project",
    "project.template.create.wizard.role_to_users_ids": "the default and the compute build the same rows from the same template",
    "res.partner.l10n_uk_reports_cis_deduction_rate": "the compute only ever sets unmatched, the default",
    "resource.resource.tz": "create sets tz from the partner, then the user, then the calendar before defaults apply, the order the compute reads",
    "rma.order.state": "without an approval request the compute keeps the stored state",
    "salary.register.wizard.include_paid": "the compute only ever sets True, the default",
    "sale.order.is_rental_order": "the compute ORs the stored value, and the default is falsy outside the rental app",
    "slide.slide.is_preview": "the compute only ever writes False, the default",
    "stock.picking.type.use_create_lots": "every compute override only ever sets True, the default",
    "stock.picking.type.use_existing_lots": "every compute override only ever sets True, the default",
    "stock.scrap.scrap_qty": "the compute resets to 1 before reading the moves, and a scrap is created before its moves",
}

PENDING: frozenset[str] = frozenset(
    {
        "hr.version.l10n_au_medicare_reduction",
        "hr.version.l10n_be_dimona_next_action",
        "hr.version.l10n_in_basic_percentage",
        "loyalty.program.portal_point_name",
        "planning.slot.allocated_percentage",
    }
)


class NoSource(RuntimeError):
    pass


@dataclass(frozen=True)
class Shape:
    field: str
    default: str
    path: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.field}  default={self.default}"


def _string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _model_declaration(cls: ast.ClassDef) -> tuple[str | None, list[str]]:
    name, inherit = None, []
    for stmt in cls.body:
        if not (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            continue
        if stmt.targets[0].id == "_name":
            name = _string(stmt.value)
        elif stmt.targets[0].id == "_inherit":
            if (single := _string(stmt.value)) is not None:
                inherit = [single]
            elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                inherit = [n for n in map(_string, stmt.value.elts) if n]
    return name, inherit


def _model_names(cls: ast.ClassDef) -> list[str]:
    name, inherit = _model_declaration(cls)
    return [name] if name else inherit


def _extends_only(cls: ast.ClassDef) -> bool:
    name, inherit = _model_declaration(cls)
    return name is None or name in inherit


def _field_call(stmt: ast.stmt) -> tuple[str, ast.Call] | None:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
    else:
        return None
    call = stmt.value
    if (
        isinstance(target, ast.Name)
        and isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "fields"
    ):
        return target.id, call
    return None


def _is_constant(node: ast.AST | None, value: bool) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def _declares_no_default(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


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


def measure(roots: list[Path] | None = None) -> list[Shape]:
    roots = [root for root in (roots or default_roots()) if root.is_dir()]
    paths = _sources(roots)
    if not paths:
        raise NoSource(
            "no Python source under " + ", ".join(map(str, roots or ["(no roots)"]))
        )
    declarations: list[tuple[bool, str, int, str, dict[str, ast.AST]]] = []
    for path in paths:
        rel = display_across_repos(path, ROOT)
        for cls in ast.walk(_ast_cache.parse_file(path)):
            if not isinstance(cls, ast.ClassDef):
                continue
            extends = _extends_only(cls)
            for model in _model_names(cls):
                for stmt in cls.body:
                    if (found := _field_call(stmt)) is None:
                        continue
                    name, call = found
                    declared = {kw.arg: kw.value for kw in call.keywords if kw.arg}
                    declarations.append(
                        (extends, rel, stmt.lineno, f"{model}.{name}", declared)
                    )
    keywords: dict[str, dict[str, ast.AST]] = {}
    default_at: dict[str, tuple[str, int]] = {}
    for _extends, rel, line, key, declared in sorted(
        declarations, key=lambda item: item[0]
    ):
        keywords.setdefault(key, {}).update(declared)
        if "default" in declared:
            default_at[key] = (rel, line)
    shapes = []
    for key, declared in sorted(keywords.items()):
        if (
            "compute" in declared
            and "related" not in declared
            and "default" in declared
            and _is_constant(declared.get("store"), True)
            and _is_constant(declared.get("readonly"), False)
            and not _declares_no_default(declared["default"])
        ):
            path, line = default_at[key]
            shapes.append(Shape(key, ast.unparse(declared["default"]), path, line))
    return shapes


def split(
    shapes: list[Shape], *, full_workspace: bool = True
) -> tuple[list[Shape], list[str]]:
    found = {shape.field for shape in shapes}
    unlisted = [s for s in shapes if s.field not in REVIEWED and s.field not in PENDING]
    stale = sorted((set(REVIEWED) | PENDING) - found) if full_workspace else []
    return unlisted, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="an editable stored compute whose class default decides its value on create"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail on an unlisted or stale field"
    )
    parser.add_argument("--count", action="store_true", help="print the pending count")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("roots", nargs="*", type=Path)
    args = parser.parse_args(argv)
    try:
        shapes = measure(args.roots or None)
    except NoSource as error:
        print(f"computed_default: {error}", file=sys.stderr)
        return 2
    unlisted, stale = split(
        shapes, full_workspace=not args.roots and in_full_workspace(ROOT)
    )
    pending = [shape for shape in shapes if shape.field in PENDING]
    if args.json:
        print(
            json.dumps(
                {
                    "unlisted": [asdict(s) for s in unlisted],
                    "stale": stale,
                    "pending": [asdict(s) for s in pending],
                    "reviewed": sorted(REVIEWED),
                },
                indent=2,
            )
        )
    elif args.count:
        print(len(pending))
    else:
        for shape in unlisted:
            print(f"UNLISTED  {shape}")
        for field in stale:
            print(f"STALE     {field} is listed but no longer declared this way")
        print(
            f"{len(shapes)} editable stored computes carry a default: "
            f"{len(shapes) - len(pending) - len(unlisted)} reviewed, "
            f"{len(pending)} pending, {len(unlisted)} unlisted, {len(stale)} stale"
        )
    if args.check:
        return 1 if unlisted or stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
