import ast
import logging
import re
import typing
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from types import SimpleNamespace
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import ACCEPTED_CONDITION_OPERATORS, Domain, DomainCondition
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL, frozendict
from odoo.tools.safe_eval import safe_eval, time

from .ir_access_reach import Part, propose, proves
from .ir_model_common import (
    ACCESS_ERROR_GROUPS,
    ACCESS_ERROR_HEADER,
    ACCESS_ERROR_NOGROUP,
    ACCESS_ERROR_RESOLUTION,
    ACCESS_ERROR_VERB,
    ACCESS_MODES,
    unloaded_module_domain,
    unloaded_module_scope,
)

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)

CRUD_SELECTION = {
    "crud": "Create, Read, Update, Delete",
    "cru": "Create, Read, Update",
    "crd": "Create, Read, Delete",
    "cud": "Create, Update, Delete",
    "rud": "Read, Update, Delete",
    "cr": "Create, Read",
    "cu": "Create, Update",
    "cd": "Create, Delete",
    "ru": "Read, Update",
    "rd": "Read, Delete",
    "ud": "Update, Delete",
    "c": "Create",
    "r": "Read",
    "u": "Update",
    "d": "Delete",
}
OPERATION_LETTER = {"create": "c", "read": "r", "write": "u", "unlink": "d"}
ANY_OPERATORS = frozenset({"any", "not any", "any!", "not any!"})
REACH_SELECTION = [
    ("none", "Nothing"),
    ("own", "Own"),
    ("team", "Team"),
    ("unit", "Unit"),
    ("unit_tree", "Unit and sub-units"),
    ("company", "Company"),
    ("partner", "Commercial partner"),
    ("all", "All"),
    ("predicate", "Named predicate"),
]
# the anchor a rung reads when the row names none
REACH_ANCHOR = {
    "own": "owner",
    "team": "team",
    "unit": "unit",
    "unit_tree": "unit",
    "company": "company",
    "partner": "partner",
}
# the anchor kinds each rung can read
REACH_KINDS = {
    "own": frozenset({"owner", "creator", "employee", "partner"}),
    "team": frozenset({"team"}),
    "unit": frozenset({"unit"}),
    "unit_tree": frozenset({"unit"}),
    "company": frozenset({"company"}),
    "partner": frozenset({"partner"}),
}
# a domain that can hold an 'access' condition: only those are parsed for the
# cycle check (an unrelated text is not evaluated, which a rule calling back
# into the decision would turn into a recursion)
ACCESS_OPERATOR_RE = re.compile(r"""['"]access['"]""")
NON_STANDARD_MODULES = ("__export__", "__custom__", "studio_customization")
INVALID_DOMAIN_ERRORS = (
    SyntaxError,
    TypeError,
    ValueError,
    NameError,
    KeyError,
    ZeroDivisionError,
)
GROUP_TESTS = frozenset(
    {
        "all_group_ids",
        "group_ids",
        "groups_id",
        "has_group",
        "has_groups",
        "_has_group",
        "_get_group_ids",
    }
)


class AccessInfo(typing.NamedTuple):
    id: int
    group_id: int
    kind: str
    guard_scope: str
    operation: str
    domain: Domain | str
    name: str = ""
    text: str = ""
    verbs: frozenset[str] = frozenset()
    reach: str = ""
    anchor: str = ""
    predicate: tuple[str, str, str, str] = ("", "", "", "")
    predicate_args: tuple[tuple[str, Any], ...] = ()


def covers(row: AccessInfo, operation: str) -> bool:
    # a CRUD operation by its letter, a declared verb by its name
    letter = OPERATION_LETTER.get(operation)
    return letter in row.operation if letter else operation in row.verbs


def parse_verbs(text: str | None) -> frozenset[str]:
    return frozenset(filter(None, (verb.strip() for verb in (text or "").split(","))))


def parse_access_domain(text: str | None) -> Domain | str:
    # a literal domain is parsed once; one that reads the user or the companies
    # stays text and is evaluated for each principal
    text = (text or "").strip()
    if not text:
        return Domain.TRUE
    try:
        return Domain(ast.literal_eval(text))
    except ValueError, SyntaxError, TypeError:
        return text


def _monotone_group_reads(tree: ast.AST) -> set[int]:
    # the two readings of the principal's groups that more groups can only
    # widen: membership in the ids of the user's groups, and an exemption that
    # drops the domain altogether for the members of a group
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            for index, item in enumerate(node.elts):
                if not (
                    isinstance(item, (ast.Tuple, ast.List))
                    and len(item.elts) == 3
                    and isinstance(item.elts[1], ast.Constant)
                    and item.elts[1].value == "in"
                ):
                    continue
                previous = node.elts[index - 1] if index else None
                if isinstance(previous, ast.Constant) and previous.value == "!":
                    continue
                value = item.elts[2]
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "ids"
                    and isinstance(value.value, ast.Attribute)
                    and value.value.attr in ("all_group_ids", "group_ids")
                ):
                    allowed.add(id(value.value))
                elif isinstance(value, ast.Name) and value.id == "group_ids":
                    allowed.add(id(value))
        elif (
            isinstance(node, ast.IfExp)
            and isinstance(node.test, ast.Call)
            and isinstance(node.test.func, ast.Attribute)
            and node.test.func.attr == "has_group"
            and _widens(node)
        ):
            allowed.add(id(node.test.func))
    return allowed


def _widens(node: ast.IfExp) -> bool:
    # [] if member else D: the members are exempt; ['|', A] if member else []
    # put before a domain: the members also reach A
    if isinstance(node.body, ast.List) and not node.body.elts:
        return True
    return (
        isinstance(node.orelse, ast.List)
        and not node.orelse.elts
        and isinstance(node.body, ast.List)
        and bool(node.body.elts)
        and isinstance(node.body.elts[0], ast.Constant)
        and node.body.elts[0].value == "|"
    )


def domain_group_tests(domain: str) -> list[str]:
    # a domain that tests the principal's groups can make a group take records
    # away; the row's group is where membership is stated
    try:
        tree = ast.parse(domain.strip(), mode="eval")
    except SyntaxError:
        return []
    allowed = _monotone_group_reads(tree)
    return sorted(
        {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in GROUP_TESTS
            and id(node) not in allowed
        }
        | {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id == "group_ids"
            and id(node) not in allowed
        }
    )


def _conditions_with_models(
    model: models.BaseModel, domain: Domain
) -> Iterator[tuple[models.BaseModel, DomainCondition]]:
    for condition in domain.iter_conditions():
        *path, last = condition.field_expr.split(".")
        owner = model
        for name in path:
            field = owner._fields.get(name)
            if field is None or not field.relational:
                break
            owner = owner.env[field.comodel_name]
        else:
            condition = DomainCondition(last, condition.operator, condition.value)
            yield owner, condition
            field = owner._fields.get(last)
            value = condition.value
            if (
                field is not None
                and field.relational
                and condition.operator in ("any", "not any", "any!", "not any!")
                and isinstance(value, (Domain, list, tuple))
            ):
                yield from _conditions_with_models(
                    owner.env[field.comodel_name], Domain(value)
                )


def access_edges(model: models.BaseModel, domain: Domain) -> Iterator[tuple[str, str]]:
    for owner, condition in _conditions_with_models(model, domain):
        if condition.operator != "access":
            continue
        field = owner._fields.get(condition.field_expr)
        if condition.value not in OPERATION_LETTER:
            raise ValueError(
                f"The 'access' operator takes one of {ACCESS_MODES}, "
                f"not {condition.value!r}"
            )
        if field is not None and field.name == "id":
            yield owner._name, condition.value
        elif field is not None and field.is_many2one:
            yield field.comodel_name, condition.value
        else:
            raise ValueError(
                f"The 'access' operator works only for many2one and 'id' fields, "
                f"not {owner._name}.{condition.field_expr}"
            )


def without_access_conditions(domain: Domain) -> Domain:
    # a domain's own validity, read without resolving what other accesses
    # allow: those rows are checked on their own
    def skip(condition: DomainCondition) -> Domain:
        if condition.operator == "access":
            return DomainCondition(condition.field_expr, "!=", False)
        if condition.operator in ("any", "not any", "any!", "not any!") and isinstance(
            condition.value, (Domain, list, tuple)
        ):
            return DomainCondition(
                condition.field_expr,
                condition.operator,
                without_access_conditions(Domain(condition.value)),
            )
        return condition

    return domain.map_conditions(skip)


def missing_fields(model: models.BaseModel, text: str) -> Iterator[str]:
    # read from the text rather than evaluated: every stored path is a
    # literal, and evaluating each row per load costs ten times the walk
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return
    yield from _missing_fields(model, tree)


def _missing_fields(model: models.BaseModel, node: ast.AST) -> Iterator[str]:
    if (
        isinstance(node, (ast.Tuple, ast.List))
        and len(node.elts) == 3
        and isinstance(path := node.elts[0], ast.Constant)
        and isinstance(path.value, str)
        and isinstance(operator := node.elts[1], ast.Constant)
        and operator.value in ACCEPTED_CONDITION_OPERATORS
    ):
        target = model
        for name in path.value.split("."):
            field = target._fields.get(name)
            if field is None:
                yield f"{target._name}.{name}"
                return
            if not field.relational:
                # what follows names a property or a date part
                return
            target = model.env[field.comodel_name]
        if operator.value in ANY_OPERATORS:
            yield from _missing_fields(target, node.elts[2])
        return
    for child in ast.iter_child_nodes(node):
        yield from _missing_fields(model, child)


PREDICATE_BINDS = frozenset(
    {
        "user",
        "partner",
        "commercial_partner",
        "companies",
        "employees",
        "teams",
        "units",
    }
)


class _Principal:
    # the binds a predicate's template reads, fetched only when read
    __slots__ = ("_bind",)

    def __init__(self, bind: typing.Callable[..., Any]) -> None:
        self._bind = bind

    def __getattr__(self, name: str) -> Any:
        if name not in PREDICATE_BINDS:
            raise AttributeError(name)
        return self._bind(name, None) if name == "teams" else self._bind(name)


KIND_OF_RUNG = {
    ("own", "owner"): "owner",
    ("own", "creator"): "creator",
    ("own", "employee"): "employee",
    ("own", "partner"): "partner",
    ("partner", "partner"): "partner",
    ("team", "team"): "team",
    ("company", "company"): "company",
}


def filter_reads_user(registry: Any, model_name: str, text: str | None) -> bool:
    # a filter naming a field whose value depends on the user (its compute
    # depends on the uid context, and a method searches it; a related field
    # depends on it only through access rights, and its search is its path):
    # such a filter is not fixed, whatever its text says
    if not text or model_name not in registry:
        return False
    try:
        leaves = ast.literal_eval(text)
    except ValueError, SyntaxError:
        return True
    if not isinstance(leaves, (list, tuple)):
        return False
    for leaf in leaves:
        if not isinstance(leaf, (list, tuple)) or len(leaf) != 3:
            continue
        current = registry[model_name]
        for name in str(leaf[0]).split("."):
            field = current._fields.get(name)
            if field is None:
                break
            if (
                not field.store
                and not field.related
                and field.search
                and "uid" in registry.field_depends_context.get(field, ())
            ):
                return True
            if not field.comodel_name or field.comodel_name not in registry:
                break
            current = registry[field.comodel_name]
    return False


def reach_values(
    anchors: Mapping[str, Any], predicates: Mapping[str, int], part: Part
) -> dict[str, Any] | None:
    # the values a proposed part writes on a row, or None when the model
    # declares no anchor it reads, or the predicate it names is not installed
    values: dict[str, Any] = {
        "reach": part.reach,
        "anchor": False,
        "domain": part.static or False,
        "predicate_id": False,
        "predicate_args": False,
    }
    if part.reach in ("all", "none"):
        return values
    if part.reach == "predicate":
        if part.predicate not in predicates:
            return None
        values["predicate_id"] = predicates[part.predicate]
        values["predicate_args"] = dict(part.args)
        return values
    kind = KIND_OF_RUNG[(part.reach, part.kind)]
    wanted = (part.path, kind, part.unset, part.hierarchy or "", part.usage or None)
    keys = [
        key
        for key, anchor in anchors.items()
        if (
            anchor.path,
            anchor.kind,
            bool(anchor.shared),
            anchor.hierarchy or "",
            anchor.usage or None,
        )
        == wanted
    ]
    if not keys:
        return None
    default = REACH_ANCHOR.get(part.reach)
    key = default if default in keys else min(keys)
    values["anchor"] = False if key == default else key
    return values


def compile_predicate(
    model: models.BaseModel,
    predicate: tuple[str, str, str, str],
    args: dict[str, Any],
    bind: typing.Callable[..., Any],
) -> Domain:
    # a named predicate's domain for the principal: its method on the model,
    # or its template reading P (the binds) and args
    _name, template, method, _description = predicate
    if method:
        return Domain(getattr(model, method)(bind, args))
    return Domain(
        safe_eval(template, {"P": _Principal(bind), "args": SimpleNamespace(**args)})
    )


def find_access_cycle(
    edges: Mapping[tuple[str, str], Iterable[tuple[str, str]]],
) -> list[tuple[str, str]] | None:
    done: set[tuple[str, str]] = set()
    for start in list(edges):
        if start in done:
            continue
        path = [start]
        stack = [iter(edges.get(start, ()))]
        while stack:
            target = next(stack[-1], None)
            if target is None:
                stack.pop()
                done.add(path.pop())
            elif target in path:
                return path[path.index(target) :] + [target]
            elif target not in done:
                path.append(target)
                stack.append(iter(edges.get(target, ())))
    return None


class IrAccess(models.Model):
    _name = "ir.access"
    _access_audit = True
    _description = "Access"
    _order = "model_id, group_id, id"
    _allow_sudo_commands = False

    name = fields.Char(required=True)
    active = fields.Boolean(
        default=True,
        help="Only active accesses are taken into account when checking access rights.",
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        index=True,
        required=True,
        ondelete="cascade",
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        index=True,
        required=True,
        ondelete="cascade",
        help="The group the row is for. A guard scoped to everyone binds every "
        "principal whatever its group; Everyone is the group of every user.",
    )
    kind = fields.Selection(
        selection=[("permission", "Permission"), ("guard", "Guard")],
        required=True,
        help="A permission adds the records of its domain to what its group may "
        "reach; the permissions a principal holds are combined with OR. A guard "
        "is combined with AND and cannot be widened by any permission.",
    )
    guard_scope = fields.Selection(
        selection=[("everyone", "Everyone"), ("members", "Members of the group")],
        default="everyone",
        required=True,
        help="Whom a guard binds: every principal, or only the members of its group.",
    )
    operation = fields.Selection(
        selection=list(CRUD_SELECTION.items()),
        help="Which operation(s) this access applies to, a subset of 'crud'.",
    )
    verbs = fields.Char(
        help="The verbs of the model this access applies to, comma-separated: "
        "operations the model declares beside create, read, update and delete, "
        "such as post or confirm. A verb's records are also within those of the "
        "operation it requires.",
    )
    domain = fields.Char(
        help="The operations are allowed only on the records in this domain. "
        "With a reach, it can only be a fixed filter that reads no user.",
    )
    reach = fields.Selection(
        selection=REACH_SELECTION,
        help="How far the row reaches, read through an anchor the model declares: "
        "the principal's own records, their team's, their unit's, their "
        "companies', their commercial partner's, all of them, or what a named "
        "predicate selects. Empty: the domain says it alone.",
    )
    anchor = fields.Char(
        help="The model's anchor the reach reads, when not the reach's own: "
        "creator, employee or a second anchor the model names.",
    )
    predicate_id = fields.Many2one(
        comodel_name="ir.access.predicate",
        ondelete="restrict",
        help="The named predicate a row with the reach Named predicate applies.",
    )
    predicate_args = fields.Json(
        help="The arguments the named predicate takes, as its schema states.",
    )
    for_read = fields.Boolean(
        string="Read",
        compute="_compute_for_read",
        inverse="_inverse_for_operations",
        search="_search_for_read",
    )
    for_write = fields.Boolean(
        string="Update",
        compute="_compute_for_write",
        inverse="_inverse_for_operations",
        search="_search_for_write",
    )
    for_create = fields.Boolean(
        string="Create",
        compute="_compute_for_create",
        inverse="_inverse_for_operations",
        search="_search_for_create",
    )
    for_unlink = fields.Boolean(
        string="Delete",
        compute="_compute_for_unlink",
        inverse="_inverse_for_operations",
        search="_search_for_unlink",
    )
    is_standard = fields.Boolean(
        compute="_compute_is_standard",
        search="_search_is_standard",
        compute_sudo=True,
        help="Whether the access is defined by a module.",
    )
    note = fields.Html()

    _operation_or_verbs = models.Constraint(
        "CHECK (operation IS NOT NULL OR verbs IS NOT NULL)",
        "An access applies to an operation, a verb, or both.",
    )

    # one compute per flag: ticking one protects only that one, so the inverse
    # reads the other three from the operation
    @api.depends("operation")
    def _compute_for_read(self) -> None:
        self._compute_for_operation("read")

    @api.depends("operation")
    def _compute_for_write(self) -> None:
        self._compute_for_operation("write")

    @api.depends("operation")
    def _compute_for_create(self) -> None:
        self._compute_for_operation("create")

    @api.depends("operation")
    def _compute_for_unlink(self) -> None:
        self._compute_for_operation("unlink")

    def _compute_for_operation(self, operation: str) -> None:
        letter = OPERATION_LETTER[operation]
        for access in self:
            access[f"for_{operation}"] = letter in (access.operation or "")

    def _inverse_for_operations(self) -> None:
        for access in self:
            operation = self._operation_of(access)
            if not operation:
                _debug.logic(
                    "operations_refused", access=access.id, reason="none_ticked"
                )
                raise ValidationError(
                    self.env._(
                        "The access %s must allow at least one operation; "
                        "archive or delete it instead.",
                        access.name,
                    )
                )
            access.operation = operation

    def _search_for_read(self, operator: str, value: Any) -> Domain:
        return self._search_for_letter("r", operator, value)

    def _search_for_write(self, operator: str, value: Any) -> Domain:
        return self._search_for_letter("u", operator, value)

    def _search_for_create(self, operator: str, value: Any) -> Domain:
        return self._search_for_letter("c", operator, value)

    def _search_for_unlink(self, operator: str, value: Any) -> Domain:
        return self._search_for_letter("d", operator, value)

    @staticmethod
    def _search_for_letter(letter: str, operator: str, value: Any) -> Domain:
        # the flags are read from the operation, never stored beside it, so
        # a migration that rewrites the operation cannot leave them behind
        if operator not in ("in", "not in"):
            return NotImplemented
        values = {bool(item) for item in value}
        if operator == "not in":
            values = {True, False} - values
        if values == {True, False}:
            return Domain.TRUE
        if not values:
            return Domain.FALSE
        holds = Domain("operation", "like", letter)
        return holds if True in values else ~holds

    @staticmethod
    def _operation_of(values: Any) -> str:
        return "".join(
            letter
            for operation, letter in OPERATION_LETTER.items()
            if values[f"for_{operation}"]
        )

    def _compute_is_standard(self) -> None:
        xids = self._get_external_ids()
        for access in self:
            access.is_standard = any(
                not xid.startswith(NON_STANDARD_MODULES) for xid in xids[access.id]
            )

    def _search_is_standard(self, operator: str, value: Any) -> Domain:
        if operator not in ("in", "not in"):
            return NotImplemented
        standard = SQL(
            "SELECT d.res_id FROM ir_model_data d "
            "WHERE d.model = %s AND d.module != ALL(%s)",
            self._name,
            list(NON_STANDARD_MODULES),
        )
        positive = (True in value) == (operator == "in")
        return Domain("id", "in" if positive else "not in", standard)

    @api.constrains("model_id", "verbs")
    def _check_verbs(self) -> None:
        for access in self:
            declared = self.env.registry.model_verbs.get(access.model_id.model, {})
            if unknown := sorted(parse_verbs(access.verbs) - declared.keys()):
                raise ValidationError(
                    self.env._(
                        "Access %(access)s names %(verbs)s, which %(model)s does not "
                        "declare.",
                        access=access.name,
                        verbs=", ".join(unknown),
                        model=access.model_id.model,
                    )
                )

    def _check_operation(self, model_name: str, operation: str) -> None:
        if operation in OPERATION_LETTER:
            return
        if operation not in self.env.registry.model_verbs.get(model_name, {}):
            raise ValueError(
                f"Invalid access operation {operation!r} on {model_name}: expected "
                f"one of {ACCESS_MODES} or a verb the model declares."
            )

    @staticmethod
    def _operation_letter(operation: str) -> str:
        if operation not in OPERATION_LETTER:
            raise ValueError(
                f"Invalid access operation {operation!r}: expected one of {ACCESS_MODES}."
            )
        return OPERATION_LETTER[operation]

    @api.constrains("model_id", "domain")
    def _check_model_name(self) -> None:
        if any(
            access.model_id.model == self._name and access.domain for access in self
        ):
            raise ValidationError(
                self.env._(
                    "Accesses with a domain can not be applied on the model Access itself."
                )
            )

    @api.constrains("active", "domain", "model_id", "operation")
    def _check_domain(self) -> None:
        eval_context = self._eval_context()
        for access in self:
            if not (access.active and access.domain):
                continue
            if tests := domain_group_tests(access.domain):
                raise ValidationError(
                    self.env._(
                        "The domain of %(access)s tests the user's groups (%(tests)s). "
                        "Group membership is what the access's group states: a domain "
                        "that reads it lets a group take records away. Put the rows on "
                        "the groups instead.",
                        access=access.name,
                        tests=", ".join(tests),
                    )
                )
            model = self.env[access.model_id.model].sudo()
            try:
                domain = Domain(safe_eval(access.domain, eval_context))
                list(access_edges(model, domain))
                without_access_conditions(domain).check(model)
            except INVALID_DOMAIN_ERRORS as e:
                _debug.logic(
                    "access_domain_invalid",
                    access=access.id,
                    model=model._name,
                    error=type(e).__name__,
                )
                raise ValidationError(
                    self.env._(
                        "Invalid domain %(domain)s: %(error)s",
                        domain=access.domain,
                        error=e,
                    )
                ) from None
        # a new cycle goes through a written row's 'access' condition
        if any("access" in (access.domain or "") for access in self):
            self._check_access_graph()

    @api.model
    def _unresolved_domains(self) -> list[tuple[Self, str]]:
        # a stored row keeps its text when a module drops a field it names
        # (a noupdate row is never reloaded), and every read of its model
        # then raises for the users it binds
        accesses = self.with_context(active_test=False).search_fetch(
            Domain("active", "=", True)
            & Domain("domain", "!=", False)
            & unloaded_module_domain(self.env, self._name),
            ["model_id", "domain", "name"],
            order="id",
        )
        registry = self.env.registry
        unresolved = [
            (access, missing)
            for access in accesses
            if access.model_id.model in registry
            for missing in missing_fields(
                self.env[access.model_id.model], access.domain
            )
        ]
        # a row reaching through an anchor its model no longer declares
        for access in self.with_context(active_test=False).search_fetch(
            Domain("active", "=", True)
            & Domain("reach", "in", list(REACH_ANCHOR))
            & unloaded_module_domain(self.env, self._name),
            ["model_id", "reach", "anchor", "name"],
            order="id",
        ):
            model_name = access.model_id.model
            key = access.anchor or REACH_ANCHOR[access.reach]
            if model_name in registry and key not in registry.model_anchors.get(
                model_name, {}
            ):
                unresolved.append((access, f"{model_name} anchor {key}"))
        return unresolved

    @api.model
    def _log_unresolved_domains(self) -> None:
        unresolved = self._unresolved_domains()
        if not unresolved:
            return
        xmlids = self.browse(
            access.id for access, _missing in unresolved
        ).get_external_id()
        for access, missing in unresolved:
            _logger.error(
                "Access %s (%s, %r) on %s: its domain names %s, which does not "
                "exist, so checking %s's access raises for every principal the "
                "row binds until the domain is corrected",
                access.id,
                xmlids.get(access.id) or "no external id",
                access.name,
                access.model_id.model,
                missing,
                access.model_id.model,
            )

    @api.constrains("reach", "anchor", "domain", "predicate_id", "model_id")
    def _check_reach(self) -> None:
        anchors = self.env.registry.model_anchors
        for access in self:
            model_name = access.model_id.model
            if not access.reach:
                if access.anchor or access.predicate_id:
                    raise ValidationError(
                        self.env._(
                            "%(access)s names an anchor or a predicate but no reach.",
                            access=access.name,
                        )
                    )
                continue
            if (access.reach == "predicate") != bool(access.predicate_id):
                raise ValidationError(
                    self.env._(
                        "%(access)s: a named predicate is the reach Named predicate, "
                        "and that reach needs one.",
                        access=access.name,
                    )
                )
            predicate_model = access.predicate_id.model_id.model
            if predicate_model and predicate_model != model_name:
                raise ValidationError(
                    self.env._(
                        "%(access)s: the predicate %(predicate)s is for %(model)s.",
                        access=access.name,
                        predicate=access.predicate_id.name,
                        model=predicate_model,
                    )
                )
            if access.reach in REACH_ANCHOR:
                key = access.anchor or REACH_ANCHOR[access.reach]
                anchor = anchors.get(model_name, {}).get(key)
                if anchor is None:
                    raise ValidationError(
                        self.env._(
                            "%(access)s reaches %(reach)s records through the anchor "
                            "%(anchor)s, which %(model)s does not declare "
                            "(_access_anchors).",
                            access=access.name,
                            reach=access.reach,
                            anchor=key,
                            model=model_name,
                        )
                    )
                if anchor.kind not in REACH_KINDS[access.reach]:
                    raise ValidationError(
                        self.env._(
                            "%(access)s: the reach %(reach)s cannot read the anchor "
                            "%(anchor)s, a %(kind)s.",
                            access=access.name,
                            reach=access.reach,
                            anchor=key,
                            kind=anchor.kind,
                        )
                    )
            elif access.anchor:
                raise ValidationError(
                    self.env._(
                        "%(access)s: the reach %(reach)s reads no anchor.",
                        access=access.name,
                        reach=access.reach,
                    )
                )
            if access.domain and (
                not isinstance(parse_access_domain(access.domain), Domain)
                or filter_reads_user(self.env.registry, model_name, access.domain)
            ):
                raise ValidationError(
                    self.env._(
                        "%(access)s: beside a reach, the domain can only be a fixed "
                        "filter; it reads the user or the companies, which is what "
                        "the reach says.",
                        access=access.name,
                    )
                )

    def _rows_to_reach(self) -> dict[str, int]:
        # the stored rows whose domain a reach or a named predicate says: each
        # proven equal and every anchor it reads declared, then written; a split
        # permission keeps its id for its first row and names the others
        # <xmlid>_2..., as the modules' files do
        env = self.env
        anchors_of = env.registry.model_anchors
        predicates = {
            predicate.name: predicate.id
            for predicate in env["ir.access.predicate"].sudo().search([])
        }
        counts = {
            "converted": 0,
            "split": 0,
            "unanchored": 0,
            "unproven": 0,
            "unreached": 0,
        }
        for access in self:
            model_name = access.model_id.model
            if model_name not in env.registry:
                continue
            proposal = propose(access.domain, access.kind)
            if access.reach == "all" and (
                proposal is None
                or filter_reads_user(env.registry, model_name, access.domain)
            ):
                # beside the reach all, a filter that reads the user is no
                # fixed filter: the row says it as the domain it is
                access.reach = False
                counts["unreached"] += 1
                continue
            if proposal is None or (
                access.reach == "all"
                and [part.reach for part in proposal.parts] == ["all"]
            ):
                continue
            if not proves(access.domain, proposal) or any(
                filter_reads_user(env.registry, model_name, part.static)
                for part in proposal.parts
            ):
                counts["unproven"] += 1
                continue
            values = [
                reach_values(anchors_of.get(model_name, {}), predicates, part)
                for part in proposal.parts
            ]
            if any(value is None for value in values):
                counts["unanchored"] += 1
                continue
            access._write_parts(typing.cast("list[dict[str, Any]]", values))
            counts["converted"] += 1
            counts["split"] += len(values) > 1
        return counts

    def _write_parts(self, parts: list[dict[str, Any]]) -> None:
        self.check_singleton()
        xmlid = self.get_external_id().get(self.id)
        data = self.env["ir.model.data"]
        if xmlid:
            module, name = xmlid.split(".", 1)
            data = data.search([("module", "=", module), ("name", "=", name)], limit=1)
        self.write(parts[0])
        for index, values in enumerate(parts[1:], start=2):
            sibling = (
                self.env.ref(f"{module}.{name}_{index}", raise_if_not_found=False)
                if xmlid
                else None
            )
            if sibling is not None and sibling._name == "ir.access":
                # the module's file split the row too, and loaded its parts
                sibling.write(values)
                continue
            extra = self.copy({"name": f"{self.name} ({index})", **values})
            if xmlid:
                data.create(
                    {
                        "module": module,
                        "name": f"{name}_{index}",
                        "model": "ir.access",
                        "res_id": extra.id,
                        "noupdate": data.noupdate,
                    }
                )

    def _row_domains(self) -> typing.Callable[[str, AccessInfo], Domain]:
        # a row's domain for the principal: its reach through the model's
        # anchor, or its predicate, and its fixed filter; else its domain
        # evaluated as it always was
        eval_context: dict[str, Any] | None = None
        binds: dict[tuple, Any] = {}

        def bind(name: str, *args: Any) -> Any:
            key = (name, *args)
            if key not in binds:
                binds[key] = getattr(self, f"_access_bind_{name}")(*args)
            return binds[key]

        def domain_of(model_name: str, row: AccessInfo) -> Domain:
            nonlocal eval_context
            if row.reach:
                static = row.domain if isinstance(row.domain, Domain) else Domain.TRUE
                return self._reach_domain(model_name, row, bind) & static
            if isinstance(row.domain, Domain):
                return row.domain
            if eval_context is None:
                eval_context = self._eval_context()
            return Domain(safe_eval(row.domain, eval_context))

        return domain_of

    def _reach_domain(
        self, model_name: str, row: AccessInfo, bind: typing.Callable[..., Any]
    ) -> Domain:
        if row.reach == "all":
            return Domain.TRUE
        if row.reach == "none":
            return Domain.FALSE
        if row.reach == "predicate":
            return compile_predicate(
                self.env[model_name], row.predicate, dict(row.predicate_args), bind
            )
        key = row.anchor or REACH_ANCHOR[row.reach]
        anchor = self.env.registry.model_anchors[model_name][key]
        path = anchor.path
        match row.reach, anchor.kind:
            case "own", "owner" | "creator":
                domain = Domain(path, "in", [bind("user")])
            case "own", "employee":
                domain = Domain(path, "in", bind("employees"))
            case "own", "partner":
                domain = Domain(path, "in", [bind("partner")])
            case "team", _:
                domain = Domain(path, "in", bind("teams", anchor.usage))
            case "unit", _:
                domain = Domain(path, "in", bind("units"))
            case "unit_tree", _:
                units = bind("units")
                domain = Domain(path, "child_of", units) if units else Domain.FALSE
            case "company", _:
                domain = Domain(path, anchor.hierarchy or "in", bind("companies"))
            case "partner", _:
                domain = Domain(path, "child_of", [bind("commercial_partner")])
            case _:
                raise ValueError(f"reach {row.reach!r} cannot read a {anchor.kind}")
        if anchor.shared:
            domain |= Domain(path, "=", False)
        return domain

    # what the rungs compare an anchor with, read once per principal; a module
    # that brings a kind of anchor brings its bind (hr: employees and units,
    # team: teams)
    def _access_bind_user(self) -> int:
        return self.env.uid

    def _access_bind_partner(self) -> int:
        return self.env.user.partner_id.id

    def _access_bind_commercial_partner(self) -> int:
        return self.env.user.commercial_partner_id.id

    def _access_bind_companies(self) -> list[int]:
        return self.env.companies.ids

    def _reach_words(self, model_name: str, row: AccessInfo) -> str:
        # what the row's reach says, for the explanation
        if row.reach in ("all", "none", ""):
            return ""
        if row.reach == "predicate":
            name, _template, _method, description = row.predicate
            return description or name
        key = row.anchor or REACH_ANCHOR[row.reach]
        anchor = self.env.registry.model_anchors.get(model_name, {}).get(key)
        if anchor is None:
            return ""
        label = anchor.path
        return self.env._(
            "%(reach)s, read through %(path)s", reach=row.reach, path=label
        )

    def _check_access_graph(self) -> None:
        rows = (
            self.sudo().with_context(active_test=False).search([("active", "=", True)])
        )
        cycle = self._access_cycle(self._access_infos(rows))
        if cycle:
            raise ValidationError(self._access_cycle_message(cycle))

    def _access_cycle_message(self, cycle: list[tuple[str, str]]) -> str:
        return self.env._(
            "The 'access' conditions of the accesses form a cycle: %(cycle)s. "
            "A record's access cannot depend on itself; break the cycle with a "
            "domain that does not go through the 'access' operator.",
            cycle=" -> ".join(f"{model}.{operation}" for model, operation in cycle),
        )

    def _access_cycle(
        self, infos: Mapping[str, tuple[AccessInfo, ...]]
    ) -> list[tuple[str, str]] | None:
        registry = self.env.registry
        edges: defaultdict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        eval_context = None
        for model_name in registry.models:
            model_class = registry[model_name]
            if model_class._abstract or not model_class._inherits_rules:
                continue
            for parent_model_name in model_class._inherits:
                for operation in OPERATION_LETTER:
                    edges[model_name, operation].add((parent_model_name, operation))
        for model_name, rows in infos.items():
            model = self.env[model_name].sudo()
            for row in rows:
                if not ACCESS_OPERATOR_RE.search(row.text):
                    continue
                domain = row.domain
                if not isinstance(domain, Domain):
                    if eval_context is None:
                        eval_context = self._eval_context()
                    try:
                        domain = Domain(safe_eval(domain, eval_context))
                    except INVALID_DOMAIN_ERRORS:
                        _logger.warning(
                            "Access %s: its domain does not evaluate",
                            row.id,
                            exc_info=True,
                        )
                        continue
                try:
                    targets = set(access_edges(model, domain))
                except ValueError:
                    continue
                for operation, letter in OPERATION_LETTER.items():
                    if letter in row.operation:
                        edges[model_name, operation].update(targets)
        return find_access_cycle(edges)

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        everyone = None
        for vals in vals_list:
            if "operation" not in vals and (
                operation := self._operation_of(
                    {f"for_{op}": vals.get(f"for_{op}") for op in OPERATION_LETTER}
                )
            ):
                vals["operation"] = operation
            if not vals.get("group_id"):
                if everyone is None:
                    everyone = self.env.ref("base.group_everyone")
                _logger.warning(
                    "Access %s has no group: it is given to %s.",
                    vals.get("name"),
                    everyone.name,
                )
                vals["group_id"] = everyone.id
        self.env.flush_all()
        accesses = super().create(vals_list)
        _debug.lifecycle("create", count=len(accesses))
        self._clear_access_caches()
        return accesses

    @api.model
    def _load_records(self, data_list: list[dict], update: bool = False) -> Self:
        # a module's rows reuse the external ids of the access lines and rules
        # they were converted from; base's 1.97 migration moves those ids onto
        # the rows before any module loads, so a database that still maps one
        # to an old record has not run it
        if old := (
            self.env["ir.model.data"]
            .sudo()
            .search([("model", "in", ("ir.model.access", "ir.rule"))], limit=1)
        ):
            raise UserError(
                self.env._(
                    "This database still holds access lines and record rules "
                    "(%(xmlid)s among them), which base's 1.97 migration converts "
                    "into ir.access rows. Upgrade base first (-u base), then the "
                    "other modules.",
                    xmlid=f"{old.module}.{old.name}",
                )
            )
        self._check_guard_scope_stated(data_list)
        return super()._load_records(data_list, update)

    def _check_guard_scope_stated(self, data_list: list[dict]) -> None:
        # a guard on a group defaults to binding every principal, which a file
        # naming a group almost never means (marin's CSV row did exactly this)
        everyone = self.env.ref("base.group_everyone", raise_if_not_found=False)
        for data in data_list:
            values = data["values"]
            if values.get("kind") != "guard" or "guard_scope" in values:
                continue
            group_id = values.get("group_id")
            if not group_id or (everyone and group_id == everyone.id):
                continue
            raise ValidationError(
                self.env._(
                    "%(file)s: the guard %(xmlid)s is on a group other than "
                    "Everyone but does not say whom it binds. State its "
                    "guard_scope: 'members' binds that group's members, "
                    "'everyone' binds every user (a CSV row that needs it goes "
                    "to security/ir_access.xml).",
                    file=self.env.context.get("install_filename")
                    or self.env.context.get("install_module")
                    or "",
                    xmlid=data.get("xml_id") or values.get("name"),
                )
            )

    def write(self, vals: dict[str, Any]) -> bool:
        _debug.lifecycle("write", count=len(self), fields=list(vals))
        self.env.flush_all()
        result = super().write(vals)
        self._clear_access_caches()
        return result

    def unlink(self) -> bool:
        _debug.lifecycle("unlink", count=len(self))
        self.env.flush_all()
        result = super().unlink()
        self._clear_access_caches()
        return result

    def _clear_access_caches(self) -> None:
        self.env.flush_all()
        self.env.invalidate_all()
        # views bake the groups a model is readable by into their cached arch
        self.env.registry.clear_cache("stable", "templates")

    def customize(self) -> dict[str, Any]:
        self.check_singleton()
        if self.is_standard:
            access = self.copy()
            self.active = False
        else:
            access = self
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": self._name,
            "res_id": access.id,
        }

    @api.model
    def _eval_context(self) -> dict[str, Any]:
        # modules extend it (website adds the current website); the user comes
        # with an empty context, so a domain reads the same in every context
        return {
            "user": self.env.user.with_context({}),
            "company_ids": self.env.companies.ids,
            "company_id": self.env.company.id,
            "group_ids": list(self.env.user._get_group_ids()),
            "ref": self._ref_id,
            "time": time,
        }

    def _ref_id(self, xmlid: str) -> int:
        # a row that names one record, typically the group a privilege grants
        return (
            self.env["ir.model.data"]
            .sudo()
            ._xmlid_to_res_id(xmlid, raise_if_not_found=True)
        )

    def _get_access_context(self) -> Iterator[Any]:
        # the context values the evaluation of a domain depends on
        company_ids = self.env.context.get("allowed_company_ids")
        yield tuple(company_ids) if isinstance(company_ids, list) else company_ids

    def _get_unloaded_module_scope(self) -> tuple[int, str | None] | None:
        return unloaded_module_scope(self.env)

    def _policy_signature(self) -> tuple:
        env = self.env
        return (
            env.uid,
            env.user._get_group_signature(),
            tuple(self._get_access_context()),
            unloaded_module_scope(env),
        )

    def _access_infos(self, accesses: Self) -> dict[str, tuple[AccessInfo, ...]]:
        result: defaultdict[str, list[AccessInfo]] = defaultdict(list)
        registry = self.env.registry
        for access in accesses:
            model_name = access.model_id.model
            if model_name not in registry:
                continue
            text = (access.domain or "").strip()
            result[model_name].append(
                AccessInfo(
                    access.id,
                    access.group_id.id,
                    access.kind,
                    access.guard_scope,
                    access.operation or "",
                    parse_access_domain(text),
                    access.name,
                    text,
                    parse_verbs(access.verbs),
                    access.reach or "",
                    access.anchor or "",
                    (
                        access.predicate_id.name or "",
                        access.predicate_id.template or "",
                        access.predicate_id.method or "",
                        access.predicate_id.description or "",
                    ),
                    tuple(sorted((access.predicate_args or {}).items())),
                )
            )
        return {model_name: tuple(infos) for model_name, infos in result.items()}

    @api.model
    @tools.ormcache("self._get_unloaded_module_scope()", cache="stable")
    def _get_all_access(self) -> frozendict:
        accesses = (
            self.sudo()
            .with_context(active_test=False)
            .search(
                Domain("active", "=", True)
                & unloaded_module_domain(self.env, self._name),
                order="id",
            )
        )
        infos = self._access_infos(accesses)
        # a model with its own table under a table-inheritance root is bound by
        # the root's rows too, as the rows are read through the root's table
        for model_name in list(self.env.registry.models):
            for other in self._get_models_bound_by(model_name)[1:]:
                infos[model_name] = infos.get(model_name, ()) + infos.get(other, ())
        if cycle := self._access_cycle(infos):
            raise ValueError(self._access_cycle_message(cycle))
        _debug.perf.count("accesses_loaded", rows=len(accesses), models=len(infos))
        return frozendict(infos)

    def _get_models_bound_by(self, model_name: str) -> list[str]:
        # a model with its own table under a table-inheritance root is bound by
        # the root's rows too, as its records are read through the root's table
        registry = self.env.registry
        model_cls = registry.get(model_name)
        root = getattr(model_cls, "_table_inheritance_root", "")
        if not root or model_cls._table == root:
            return [model_name]
        return [model_name] + [
            name
            for name in registry.model_names_by_inheritance_root.get(root, ())
            if registry[name]._table == root
        ]

    def _bound_access_rows(
        self, model_name: str, operation: str
    ) -> tuple[list[Domain], list[Domain]]:
        # the domains of the permissions the principal's groups hold and of the
        # guards that bind it, for one model and operation
        self._check_operation(model_name, operation)
        scopes = self.env.user._get_group_scopes()
        permissions: list[Domain] = []
        guards: list[Domain] = []
        domain_of = self._row_domains()
        for row in self._get_all_access().get(model_name, ()):
            if not covers(row, operation):
                continue
            binds = row.kind == "guard" and row.guard_scope == "everyone"
            if not binds and row.group_id not in scopes:
                continue
            domain = domain_of(model_name, row)
            if not binds:
                domain = self._scoped(model_name, row, domain, scopes[row.group_id])
            (permissions if row.kind == "permission" else guards).append(domain)
        return permissions, guards

    def _scoped(
        self,
        model_name: str,
        row: AccessInfo,
        domain: Domain,
        companies: frozenset[int] | None,
    ) -> Domain:
        # a row held through a grant limited to some companies reaches the
        # records of those companies (and the shared ones); a guard of the
        # members binds them there only. A model with no company anchor takes
        # the row whole: the grant holds in it wherever it is in use
        if companies is None:
            return domain
        within = self._company_scope_domain(model_name, companies)
        if within is None:
            return domain
        return domain & within if row.kind == "permission" else domain | ~within

    def _privilege_domain(self, model_name: str, operation: str) -> Domain:
        # what the environment's privileges alone allow on the model: the OR of
        # their own permission rows, the user's groups set aside
        self._check_operation(model_name, operation)
        privileges = self.env.privileges
        domain_of = self._row_domains()
        domains = [
            domain_of(model_name, row)
            for row in self._get_all_access().get(model_name, ())
            if row.kind == "permission"
            and row.group_id in privileges
            and covers(row, operation)
        ]
        return Domain.OR(domains) if domains else Domain.FALSE

    def _explain(self, model_name: str, operation: str) -> list[str]:
        # the rows that bind the principal for the operation, in words: each
        # with the group that carries it and the companies that group is held
        # in, and a note where the model belongs to no company, so a grant
        # limited to some companies applies to all its records
        self._check_operation(model_name, operation)
        scopes = self.env.user._get_group_scopes()
        groups = self.env["res.groups"].sudo()
        companies = self.env["res.company"].sudo()
        anchor = self.env[model_name]._access_company_anchor()
        lines = []
        for row in self._get_all_access().get(model_name, ()):
            if not covers(row, operation):
                continue
            if words := self._reach_words(model_name, row):
                row = row._replace(name=f"{row.name} ({words})")
            if row.kind == "guard" and row.guard_scope == "everyone":
                lines.append(self.env._("guard %(row)s, for everyone", row=row.name))
                continue
            if row.group_id not in scopes:
                continue
            group = groups.browse(row.group_id).full_name
            scope = scopes[row.group_id]
            if scope is None:
                lines.append(
                    self.env._(
                        "%(kind)s %(row)s, held through %(group)s in every company",
                        kind=row.kind,
                        row=row.name,
                        group=group,
                    )
                )
                continue
            names = ", ".join(companies.browse(sorted(scope)).mapped("name"))
            if anchor:
                lines.append(
                    self.env._(
                        "%(kind)s %(row)s, held through %(group)s in %(companies)s "
                        "only: it reaches their records and the shared ones",
                        kind=row.kind,
                        row=row.name,
                        group=group,
                        companies=names,
                    )
                )
            else:
                lines.append(
                    self.env._(
                        "%(kind)s %(row)s, held through %(group)s in %(companies)s "
                        "only; %(model)s belongs to no company, so it applies to "
                        "every record while one of those companies is in use",
                        kind=row.kind,
                        row=row.name,
                        group=group,
                        companies=names,
                        model=model_name,
                    )
                )
        return lines

    def _company_scope_domain(
        self, model_name: str, companies: frozenset[int]
    ) -> Domain | None:
        anchor = self.env[model_name]._access_company_anchor()
        if not anchor:
            return None
        company_ids = sorted(companies)
        if anchor == "id":
            return Domain("id", "in", company_ids)
        return Domain(anchor, "in", company_ids) | Domain(anchor, "=", False)

    def _get_groups_with_access(self, model_name: str, operation: str) -> Any:
        # the groups whose members may perform the operation on some records of
        # the model: a permission's group or a group implying it, for which the
        # 'access' conditions of the row, the guards binding it, the model's own
        # guard and every delegated parent can all hold
        return (
            self.env["res.groups"]
            .sudo()
            .browse(sorted(self._group_ids_with_access(model_name, operation)))
        )

    @tools.ormcache("model_name", "operation", cache="stable")
    def _group_ids_with_access(self, model_name: str, operation: str) -> frozenset[int]:
        self._check_operation(model_name, operation)
        implying = self._group_ids_implying()
        every_group = frozenset(implying)
        model = self.env[model_name].sudo()
        rows = [
            row
            for row in self._get_all_access().get(model_name, ())
            if covers(row, operation)
        ]
        groups: set[int] = set()
        for row in rows:
            if row.kind == "permission":
                groups |= implying.get(row.group_id, frozenset()) & (
                    self._group_ids_satisfying(model, self._row_access_domain(row))
                )
        for row in rows:
            if row.kind == "guard":
                allowed = self._group_ids_satisfying(
                    model, self._row_access_domain(row)
                )
                if row.guard_scope == "members":
                    allowed |= every_group - implying.get(row.group_id, frozenset())
                groups &= allowed
        groups &= self._group_ids_satisfying(model, model._access_guard(operation))
        if verb := self.env.registry.model_verbs.get(model_name, {}).get(operation):
            return frozenset(groups) & self._group_ids_with_access(
                model_name, verb.requires
            )
        if model._inherits_rules:
            for parent_model_name, field_name in model._inherits.items():
                if operation == "create" and not model._fields[field_name].store:
                    continue
                groups &= self._group_ids_with_access(parent_model_name, operation)
        return frozenset(groups)

    @tools.ormcache(cache="stable")
    def _group_ids_implying(self) -> frozendict:
        groups = self.env["res.groups"].sudo().with_context(active_test=False)
        return frozendict(
            {
                group.id: frozenset(group.all_implied_by_ids.ids) | {group.id}
                for group in groups.search([])
            }
        )

    def _row_access_domain(self, row: AccessInfo) -> Domain:
        # what a group needs of a row is only its 'access' conditions, the rest
        # can hold for some records whatever the group; a text domain is read
        # only when it can hold such a condition
        if isinstance(row.domain, Domain):
            return row.domain
        if not ACCESS_OPERATOR_RE.search(row.text):
            return Domain.TRUE
        try:
            return Domain(safe_eval(row.domain, self._eval_context()))
        except INVALID_DOMAIN_ERRORS:
            _logger.warning("Access %s: its domain does not evaluate", row.id)
            return Domain.TRUE

    def _group_ids_satisfying(
        self, model: models.BaseModel, domain: Domain
    ) -> frozenset[int]:
        every_group = frozenset(self._group_ids_implying())

        def combine(domain: Domain) -> frozenset[int]:
            if domain.is_true():
                return every_group
            if domain.is_false():
                return frozenset()
            if isinstance(domain, DomainCondition):
                comodel_name = (
                    model._name
                    if domain.field_expr == "id"
                    else model._fields[domain.field_expr].comodel_name
                )
                return self._group_ids_with_access(comodel_name, domain.value)
            operator = getattr(domain, "OPERATOR", None)
            if operator == "|":
                return frozenset().union(*map(combine, domain.children))
            if operator == "&":
                result = every_group
                for child in domain.children:
                    result &= combine(child)
                return result
            if operator == "!":
                return every_group - combine(domain.child)
            return every_group

        return combine(
            domain.map_conditions(
                lambda condition: (
                    condition if condition.operator == "access" else Domain.TRUE
                )
            )
        )

    def _group_names_with_access(self, model_name: str, operation: str) -> list[str]:
        # a group implying another group of the list adds nothing to read
        # a privilege is code's, not a group anyone can be given
        groups = self._get_groups_with_access(model_name, operation).filtered(
            lambda group: not group.is_privilege
        )
        shown = groups.filtered(
            lambda group: not ((group.all_implied_ids - group) & groups)
        )
        names = sorted(
            ((group.privilege_id.name or None, group.name) for group in shown),
            key=lambda pair: (pair[0] is None, pair[0] or "", pair[1]),
        )
        return [
            f"{privilege}/{group}" if privilege else group for privilege, group in names
        ]

    def _make_model_access_error(self, model_name: str, operation: str) -> AccessError:
        _logger.info(
            "Access Denied by ACLs for operation: %s, uid: %s, model: %s",
            operation,
            self.env.uid,
            model_name,
        )
        operation_error = str(ACCESS_ERROR_HEADER.get(operation, ACCESS_ERROR_VERB)) % {
            "document_kind": self.env["ir.model"]._get(model_name).name or model_name,
            "document_model": model_name,
            "verb": operation,
        }
        groups = "\n".join(
            f"\t- {name}"
            for name in self._group_names_with_access(model_name, operation)
        )
        if groups:
            group_info = str(ACCESS_ERROR_GROUPS) % {"groups_list": groups}
        else:
            group_info = str(ACCESS_ERROR_NOGROUP)
        return AccessError(
            "\n\n".join([operation_error, group_info, str(ACCESS_ERROR_RESOLUTION)])
        )

    def _make_record_access_error(self, records: Any, operation: str) -> AccessError:
        _logger.info(
            "Access Denied by record rules for operation: %s on record ids: %r, uid: %s, model: %s",
            operation,
            records.ids[:6],
            self.env.uid,
            records._name,
        )
        self = self.with_context(self.env.user.context_get())
        model_name = records._name
        description = self.env["ir.model"]._get(model_name).name or model_name
        operation_names = {
            "read": self.env._("read"),
            "write": self.env._("write"),
            "create": self.env._("create"),
            "unlink": self.env._("unlink"),
        }
        operation_error = self.env._(
            "Uh-oh! Looks like you have stumbled upon some top-secret records.\n\n"
            "Sorry, %(user)s doesn't have '%(operation)s' access to:",
            user=f"{self.env.user.name} (id={self.env.uid})",
            operation=operation_names.get(operation, operation),
        )
        failing_model = self.env._(
            "- %(description)s (%(model)s)", description=description, model=model_name
        )
        resolution_info = self.env._(
            "If you really, really need access, perhaps you can win over your "
            "friendly administrator with a batch of freshly baked cookies."
        )
        debug = (
            self.env.user.has_group("base.group_no_one")
            and self.env.user._is_internal()
        )
        display_records = records[:6].sudo()
        failing = self._get_failed_accesses(records, operation)
        company_related = any("company_id" in row.text for row in failing)
        context = None
        if company_related:
            resolution_info, context = self._get_company_resolution_info(
                display_records, resolution_info
            )

        def describe(record: Any) -> str:
            if (
                company_related
                and "company_id" in record
                and record.company_id in self.env.user.company_ids
            ):
                return (
                    f"{description}, {record.display_name} ({model_name}: "
                    f"{record.id}, company={record.company_id.display_name})"
                )
            return f"{description}, {record.display_name} ({model_name}: {record.id})"

        if debug:
            failing_records = "\n".join(
                f"- {describe(record)}" for record in display_records
            )
            blame = "\n\n".join(self._blame(failing))
            if any(
                scope is not None
                for scope in self.env.user._get_group_scopes().values()
            ):
                # a principal holding a group in some companies only is told
                # where each row that binds it holds
                lines = "\n".join(
                    f"- {line}" for line in self._explain(model_name, operation)
                )
                blame += f"\n\n{self.env._('What binds you:')}\n{lines}"
            message = (
                f"{operation_error}\n{failing_records}\n\n{blame}\n\n{resolution_info}"
            )
        else:
            message = f"{operation_error}\n{failing_model}\n\n{resolution_info}"
        records.invalidate_recordset()
        exception = AccessError(message)
        if context:
            exception.context = context
        return exception

    def _get_company_resolution_info(
        self, display_records: Any, resolution_info: str
    ) -> tuple[str, dict | None]:
        context = None
        suggested_companies = display_records._get_redirect_suggested_company()
        _debug.logic(
            "access_error_company_hint",
            uid=self.env.uid,
            suggested=len(suggested_companies) if suggested_companies else 0,
            reachable=bool(suggested_companies)
            and suggested_companies in self.env.user.company_ids,
        )
        if suggested_companies and len(suggested_companies) != 1:
            resolution_info += self.env._(
                "\n\nNote: this might be a multi-company issue. Switching company may help - in Odoo, not in real life!"
            )
        elif suggested_companies and suggested_companies in self.env.user.company_ids:
            context = {
                "suggested_company": {
                    "id": suggested_companies.id,
                    "display_name": suggested_companies.display_name,
                }
            }
            resolution_info += self.env._(
                "\n\nThis seems to be a multi-company issue, you might be able to access the record by switching to the company: %s.",
                suggested_companies.display_name,
            )
        elif suggested_companies:
            resolution_info += self.env._(
                "\n\nThis seems to be a multi-company issue, but you do not have access to the proper company to access the record anyhow."
            )
        return resolution_info, context

    def _blame(self, failing: list[AccessInfo]) -> list[str]:
        accesses = sorted(
            {(row.id, row.name): row for row in failing}.values(),
            key=lambda row: (row.id == 0, row.id, row.name),
        )
        return [
            self.env._(
                "Blame the following accesses:\n%s",
                "\n".join(f"- {row.name}" for row in accesses),
            )
        ]

    def _get_failed_accesses(self, records: Any, operation: str) -> list[AccessInfo]:
        # the rows, the model's own guard and the delegated parents' rows that
        # refuse some of the records: permissions fail together (they add up),
        # each guard fails on its own
        self._check_operation(records._name, operation)
        letter = OPERATION_LETTER.get(operation, "")
        user_model = records.browse()
        model = user_model.sudo().with_context(active_test=False)
        scopes = self.env.user._get_group_scopes()
        row_domain = self._row_domains()

        def domain_of(row: AccessInfo) -> Domain:
            domain = row_domain(model._name, row)
            if row.group_id in scopes and not (
                row.kind == "guard" and row.guard_scope == "everyone"
            ):
                domain = self._scoped(model._name, row, domain, scopes[row.group_id])
            return domain

        # counted in SQL: evaluating in Python would fill the cache of the
        # records' prefetch batch with values the principal may not read
        ids = list(dict.fromkeys(id_ for id_ in records._ids if id_))

        def admitted(target: models.BaseModel, domain: Domain, among: list) -> set:
            return set(target.search(domain & Domain("id", "in", among))._ids)

        def admits_all(domain: Domain) -> bool:
            return len(admitted(model, domain, ids)) == len(ids)

        def holds(row: AccessInfo) -> bool:
            return row.group_id in scopes

        rows = [
            row
            for row in self._get_all_access().get(model._name, ())
            if covers(row, operation)
        ]
        permissions = [row for row in rows if row.kind == "permission" and holds(row)]
        failing: list[AccessInfo] = []
        if not admits_all(Domain.OR(domain_of(row) for row in permissions)):
            failing.extend(permissions)
        failing.extend(
            row
            for row in rows
            if row.kind == "guard"
            and (row.guard_scope == "everyone" or holds(row))
            and not admits_all(domain_of(row))
        )
        own = user_model._access_guard(operation)
        if not own.is_true() and not admits_all(own):
            failing.append(
                AccessInfo(
                    0,
                    0,
                    "guard",
                    "everyone",
                    letter,
                    own,
                    self.env._("the condition of %(model)s itself", model=model._name),
                    str(own),
                )
            )
        if model._inherits_rules:
            policy = self.env.registry.access_policy
            for parent_model_name, field_name in model._inherits.items():
                if operation == "create" and not model._fields[field_name].store:
                    continue
                parent_ids = list(dict.fromkeys(model.browse(ids)[field_name]._ids))
                parent = (
                    self.env[parent_model_name].sudo().with_context(active_test=False)
                )
                parent_domain = policy.security_domain(
                    self.env, parent_model_name, operation
                )
                allowed = admitted(parent, parent_domain, parent_ids)
                refused = [id_ for id_ in parent_ids if id_ not in allowed]
                if not refused:
                    continue
                through = self.env._(
                    "through %(field)s, %(model)s",
                    field=field_name,
                    model=parent_model_name,
                )
                parent_failing = self._get_failed_accesses(
                    self.env[parent_model_name].browse(refused), operation
                ) or [
                    AccessInfo(
                        0,
                        0,
                        "permission",
                        "everyone",
                        letter,
                        Domain.FALSE,
                        self.env._("no permission"),
                        "",
                    )
                ]
                failing.extend(
                    row._replace(name=f"{row.name} ({through})")
                    for row in parent_failing
                )
        return failing
