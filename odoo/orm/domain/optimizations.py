import functools
import logging
import operator
import typing
import warnings
from collections.abc import Set as AbstractSet

from odoo.exceptions import MissingError
from odoo.tools import SQL, OrderedSet, partition, str2bool

from ..primitives import COLLECTION_TYPES
from .ast import (
    _FALSE_DOMAIN,
    _MERGE_OPTIMIZATIONS,
    _OPTIMIZATION_KEY_KIND,
    _OPTIMIZATIONS_FOR,
    _TRUE_DOMAIN,
    ANY_TYPES,
    Domain,
    DomainAnd,
    DomainCondition,
    DomainNary,
    DomainOr,
    OptimizationLevel,
    _nary_value_tiebreak,
)
from .constants import (
    ACCEPTED_CONDITION_OPERATORS,
    INVERSE_OPERATOR,
    LIKE_CONDITION_OPERATORS,
    NEGATIVE_CONDITION_OPERATORS,
)

if typing.TYPE_CHECKING:
    from collections.abc import Collection

    from ..models import BaseModel

_logger = logging.getLogger("odoo.domains")


def _check_operators(caller: str, operators: Collection[str]) -> None:
    if not operators:
        raise ValueError(f"{caller}() requires at least one operator")
    if unknown := set(operators) - ACCEPTED_CONDITION_OPERATORS:
        raise ValueError(
            f"unknown domain operator(s) {sorted(unknown)!r}. Framework "
            f"operators are declared in domain/constants.py "
            f"(STANDARD_CONDITION_OPERATORS or EXTENDED_CONDITION_OPERATORS) "
            f"and addon operators are contributed by calling "
            f"register_condition_operators() before this decorator runs; "
            f"registering an optimization no longer creates one, so this is "
            f"either a typo, a missing declaration, or a registration that "
            f"happens too late."
        )


def _register_condition_optimization(
    keys: Collection[str], level: OptimizationLevel, kind: str
) -> typing.Callable[[typing.Any], typing.Any]:
    def register(optimization: typing.Any) -> typing.Any:
        mapping = _OPTIMIZATIONS_FOR[level]
        for key in keys:
            claimed = _OPTIMIZATION_KEY_KIND.setdefault(key, kind)
            if claimed != kind:
                raise ValueError(
                    f"{key!r} is already registered as a domain {claimed} and "
                    f"cannot also be a {kind}: condition optimisations are "
                    f"looked up by operator and by field type against one "
                    f"mapping, so a name in both key spaces would run each "
                    f"other's optimisations"
                )
            mapping[key].append(optimization)
        return optimization

    return register


def operator_optimization(
    operators: Collection[str],
    level: OptimizationLevel = OptimizationLevel.BASIC,
) -> typing.Callable[[typing.Any], typing.Any]:
    _check_operators("operator_optimization", operators)
    return _register_condition_optimization(operators, level, "operator")


def field_type_optimization(
    field_types: Collection[str],
    level: OptimizationLevel = OptimizationLevel.BASIC,
) -> typing.Callable[[typing.Any], typing.Any]:
    if not field_types:
        raise ValueError("field_type_optimization() requires at least one field type")
    return _register_condition_optimization(field_types, level, "field_type")


def nary_optimization(optimization: typing.Any) -> typing.Any:
    if not hasattr(optimization, "_match_operators"):
        optimization._match_operators = None
    _MERGE_OPTIMIZATIONS.append(optimization)
    return optimization


def nary_condition_optimization(
    operators: Collection[str], field_types: Collection[str] | None = None
) -> typing.Callable[[typing.Any], typing.Any]:
    _check_operators("nary_condition_optimization", operators)

    def register(optimization: typing.Any) -> typing.Any:
        def optimizer(
            cls: type[DomainNary], domains: list[Domain], model: BaseModel
        ) -> list[Domain]:
            result = []
            merge_conditions: list[DomainCondition] = []

            def flush() -> None:
                if len(merge_conditions) >= 2:
                    result.extend(optimization(cls, merge_conditions, model))
                else:
                    result.extend(merge_conditions)

            for domain in domains:
                if isinstance(domain, DomainCondition) and domain.operator in operators:
                    field = domain._field(model)
                    if field_types is None or field.type in field_types:
                        if (
                            merge_conditions
                            and merge_conditions[0].field_expr == domain.field_expr
                        ):
                            merge_conditions.append(domain)
                            continue
                        flush()
                        merge_conditions = [domain]
                        continue
                if merge_conditions:
                    flush()
                    merge_conditions = []
                result.append(domain)
            flush()
            return result

        optimizer._match_operators = frozenset(operators)  # type: ignore[attr-defined]
        nary_optimization(optimizer)

        return optimization

    return register


@operator_optimization(["=?"])
def _operator_equal_if_value(condition, _):
    if not condition.value:
        return _TRUE_DOMAIN
    return DomainCondition(condition.field_expr, "=", condition.value)


@operator_optimization(["<>"])
def _operator_different(condition, _):
    warnings.warn(
        "Operator '<>' is deprecated since 19.0, use '!=' directly",
        DeprecationWarning,
        stacklevel=2,
    )
    return DomainCondition(condition.field_expr, "!=", condition.value)


@operator_optimization(["=="])
def _operator_equals(condition, _):
    warnings.warn(
        "Operator '==' is deprecated since 19.0, use '=' directly",
        DeprecationWarning,
        stacklevel=2,
    )
    return DomainCondition(condition.field_expr, "=", condition.value)


@operator_optimization(["=", "!="])
def _operator_equal_as_in(condition, _):
    value = condition.value
    operator = "in" if condition.operator == "=" else "not in"
    if isinstance(value, COLLECTION_TYPES):
        if not value:
            _logger.debug(
                "The domain condition %r should compare with False.", condition
            )
            value = OrderedSet([False])
        else:
            _logger.debug(
                "The domain condition %r should use the 'in' or 'not in' operator.",
                condition,
            )
            value = OrderedSet(value)
    elif isinstance(value, SQL):
        value = SQL("(%s)", value)
    else:
        value = OrderedSet((value,))
    return DomainCondition(condition.field_expr, operator, value)


@operator_optimization(["in", "not in"])
def _optimize_in_set(condition, _model):
    value = condition.value
    if isinstance(value, OrderedSet) and value:
        return condition
    if isinstance(value, ANY_TYPES):
        operator = "any" if condition.operator == "in" else "not any"
        return DomainCondition(condition.field_expr, operator, value)
    if not value:
        return _FALSE_DOMAIN if condition.operator == "in" else _TRUE_DOMAIN
    if not isinstance(value, COLLECTION_TYPES):
        _logger.debug("The domain condition %r should have a list value.", condition)
        value = [value]
    return DomainCondition(condition.field_expr, condition.operator, OrderedSet(value))


@operator_optimization(["in", "not in"])
def _optimize_in_set_falsy_value(condition, model):
    value = condition.value
    if not isinstance(value, OrderedSet):
        return condition
    falsy = condition._field(model).falsy_value
    has_falsy_alias = falsy is not None and falsy is not False

    if None not in value and not (has_falsy_alias and falsy in value):
        return condition

    def is_null_alias(v):
        return v is None or (has_falsy_alias and v is not False and v == falsy)

    if not any(is_null_alias(v) for v in value):
        return condition

    return DomainCondition(
        condition.field_expr,
        condition.operator,
        OrderedSet(False if is_null_alias(v) else v for v in value),
    )


@operator_optimization(["in", "not in"], OptimizationLevel.FULL)
def _optimize_in_required(condition, model):
    value = condition.value
    if False not in value:
        return condition
    field = condition._field(model)
    if (
        field.falsy_value is None
        and (field.required or field.name == "id")
        and field in model.env.registry.not_null_fields
        and all(model._ids)
    ):
        stripped = DomainCondition(
            condition.field_expr,
            condition.operator,
            OrderedSet(v for v in value if v is not False),
        )
        object.__setattr__(stripped, "_predicate_fallback", condition)
        return stripped
    return condition


@operator_optimization(["any", "not any", "any!", "not any!"])
def _optimize_any_domain(condition, model):
    value = condition.value
    if isinstance(value, ANY_TYPES) and not isinstance(value, Domain):
        if condition.operator in ("any", "not any"):
            return DomainCondition(
                condition.field_expr, condition.operator + "!", condition.value
            )
        return condition
    domain = Domain(value)
    field = condition._field(model)
    if field.name == "id":
        return domain if condition.operator in ("any", "any!") else ~domain
    if value is domain:
        return condition
    return DomainCondition(condition.field_expr, condition.operator, domain)


def _optimize_any_domain_at_level(level: OptimizationLevel, condition, model):
    domain = condition.value
    if not isinstance(domain, Domain):
        return condition
    field = condition._field(model)
    if not field.relational:
        raise condition._prepare_condition_error(
            "Cannot use 'any' with non-relational fields"
        )
    try:
        comodel = model.env[field.comodel_name]
    except KeyError:
        raise condition._prepare_condition_error(
            "Cannot determine the comodel relation"
        ) from None
    domain = domain._optimize(comodel, level)
    if domain.is_false():
        return _FALSE_DOMAIN if condition.operator in ("any", "any!") else _TRUE_DOMAIN
    if domain is condition.value:
        return condition
    return DomainCondition(condition.field_expr, condition.operator, domain)


for _level in OptimizationLevel:
    if _level > OptimizationLevel.NONE:
        operator_optimization(("any", "not any", "any!", "not any!"), _level)(
            functools.partial(_optimize_any_domain_at_level, _level)
        )
del _level


@operator_optimization(LIKE_CONDITION_OPERATORS)
def _optimize_like_str(condition, model):
    value = condition.value
    if not value:
        result = (condition.operator in NEGATIVE_CONDITION_OPERATORS) == (
            "=" in condition.operator
        )
        if condition._field(model).relational or "=" in condition.operator:
            return DomainCondition(condition.field_expr, "!=" if result else "=", False)
        return Domain(result)
    if isinstance(value, str) and not value.strip("%"):
        result = condition.operator not in NEGATIVE_CONDITION_OPERATORS
        if condition._field(model).relational:
            return DomainCondition(condition.field_expr, "!=" if result else "=", False)
        return Domain(result)
    if isinstance(value, str):
        return condition
    if isinstance(value, SQL):
        warnings.warn(
            "Since 19.0, use Domain.custom(to_sql=lambda model, alias, query: SQL(...))",
            DeprecationWarning,
            stacklevel=2,
        )
        return condition
    if "=" in condition.operator:
        raise condition._prepare_condition_error(
            "The pattern to match must be a string", error=TypeError
        )
    return DomainCondition(condition.field_expr, condition.operator, str(value))


_NOT_A_NUMBER = object()


def _coerce_numeric(value: typing.Any, field_type: str) -> typing.Any:
    if type(value) is not str:
        return value
    convert = int if field_type == "integer" else float
    try:
        return convert(value)
    except ValueError:
        pass
    if convert is int:
        try:
            return float(value)
        except ValueError:
            pass
    return _NOT_A_NUMBER


@field_type_optimization(["integer", "float", "monetary"])
def _optimize_numeric_comparand(condition, model):
    operator = condition.operator
    value = condition.value
    if operator not in ("in", "not in", ">", "<", ">=", "<=") or (
        "." in condition.field_expr
    ):
        return condition

    field = condition._field(model)
    if field.falsy_value is None:
        return condition

    is_collection = isinstance(value, COLLECTION_TYPES)
    if is_collection:
        if not any(type(v) is str for v in value):
            return condition
    elif type(value) is not str:
        return condition

    field_type = field.type
    if is_collection:
        coerced = [_coerce_numeric(v, field_type) for v in value]
        if _NOT_A_NUMBER in coerced:
            coerced = [v for v in coerced if v is not _NOT_A_NUMBER]
        elif coerced == list(value):
            return condition
        return DomainCondition(condition.field_expr, operator, type(value)(coerced))
    coerced = _coerce_numeric(value, field_type)
    if coerced is _NOT_A_NUMBER:
        if operator in ("in", "not in"):
            return Domain(operator == "not in")
        raise condition._prepare_condition_error(
            "Cannot compare the numeric field %r with a non-numeric value",
            condition.field_expr,
        )
    if coerced is value:
        return condition
    return DomainCondition(condition.field_expr, operator, coerced)


@field_type_optimization(
    ["many2one", "many2one_reference", "one2many", "many2many"],
)
def _optimize_relational_falsy_id(condition, model):
    operator = condition.operator
    if operator not in ("in", "not in", ">", "<", ">=", "<="):
        return condition
    if operator not in ("in", "not in") and condition._field(model).type not in (
        "many2one",
        "many2one_reference",
    ):
        return condition

    def is_falsy_id(value):
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and not value
        )

    value = condition.value
    if isinstance(value, COLLECTION_TYPES):
        if isinstance(value, AbstractSet) and 0 not in value:
            return condition
        if not any(is_falsy_id(v) for v in value):
            return condition
        return DomainCondition(
            condition.field_expr,
            operator,
            OrderedSet(False if is_falsy_id(v) else v for v in value),
        )
    if not is_falsy_id(value):
        return condition
    return DomainCondition(condition.field_expr, operator, False)


@field_type_optimization(["boolean"])
def _optimize_boolean_in(condition, model):
    value = condition.value
    operator = condition.operator
    if operator not in ("in", "not in"):
        raise condition._prepare_condition_error(
            "Operator %r is not supported on boolean field %r",
            operator,
            condition.field_expr,
        )
    if not isinstance(value, COLLECTION_TYPES):
        raise condition._prepare_condition_error(
            "Cannot compare boolean field %r to %s which is not a collection",
            condition.field_expr,
            type(value),
        )
    if not all(isinstance(v, bool) for v in value):
        if any(isinstance(v, str) for v in value):
            _logger.debug("Comparing boolean with a string in %s", condition)
        value = {
            str2bool(v.lower(), False) if isinstance(v, str) else bool(v) for v in value
        }
    if len(value) == 1 and not any(value):
        operator = INVERSE_OPERATOR[operator]
        value = [True]
    if operator == condition.operator and value is condition.value:
        return condition
    return DomainCondition(condition.field_expr, operator, value)


@field_type_optimization(["boolean"], OptimizationLevel.FULL)
def _optimize_boolean_in_all(condition, model):
    if isinstance(condition.value, COLLECTION_TYPES) and set(condition.value) == {
        False,
        True,
    }:
        return Domain(condition.operator == "in")
    return condition


@operator_optimization([">", "<", ">=", "<="])
def _optimize_inequality_against_null(condition, model):
    value = condition.value
    if value is not False and value is not None:
        return condition
    if "." in condition.field_expr:
        return condition
    if condition._field(model).falsy_value is not None:
        return condition
    return _FALSE_DOMAIN


@operator_optimization([">", "<", ">=", "<="])
def _optimize_inequality_against_collection(condition, model):
    value = condition.value
    if isinstance(value, COLLECTION_TYPES):
        raise condition._prepare_condition_error(
            "Cannot compare %r with a collection using %r; an ordering "
            "comparison takes a single value",
            condition.field_expr,
            condition.operator,
            error=TypeError,
        )
    return condition


@operator_optimization(["parent_of", "child_of"], OptimizationLevel.FULL)
def _operator_hierarchy(condition, model):
    hierarchy: typing.Callable[..., typing.Any]
    if condition.operator == "parent_of":
        hierarchy = _operator_parent_of_domain
    else:
        hierarchy = _operator_child_of_domain
    value = condition.value
    if value is False:
        return _FALSE_DOMAIN
    if value is True:
        raise condition._prepare_condition_error("True is not a valid hierarchy value")
    field = condition._field(model)
    if field.is_many2one:
        comodel = model.env[field.comodel_name].with_context(active_test=False)
    elif field.is_x2many:
        comodel = model.env[field.comodel_name].with_context(**field.context)
    elif field.name == "id":
        comodel = model
    else:
        raise condition._prepare_condition_error(
            f"Cannot execute {condition.operator} for {field}, works only for relational fields"
        )
    comodel_sudo = comodel.sudo().with_context(active_test=False)
    parent = comodel._parent_name
    if comodel._name == model._name:
        if condition.field_expr != "id":
            parent = condition.field_expr
        if field.is_many2one:
            field = model._fields["id"]
    if isinstance(value, (int, str)):
        value = [value]
    elif not isinstance(value, COLLECTION_TYPES):
        raise condition._prepare_condition_error(
            f"Value of type {type(value)} is not supported"
        )
    if any(isinstance(v, bool) for v in value):
        if any(v is True for v in value):
            raise condition._prepare_condition_error(
                "True is not a valid hierarchy value"
            )
        value = [v for v in value if v is not False]
    coids, other_values = partition(lambda v: isinstance(v, int), value)
    search_domain: Domain = _FALSE_DOMAIN
    if field.is_many2many:
        search_domain |= DomainCondition("id", "in", coids)
        coids = []
    if other_values:
        search_domain |= Domain.OR(
            Domain("display_name", "ilike", v) for v in other_values
        )
    coids += comodel.search(search_domain, order="id").ids
    if not coids:
        return _FALSE_DOMAIN
    result = hierarchy(comodel_sudo.browse(coids), parent)
    if isinstance(result, Domain):
        if field.name == "id":
            return result
        return DomainCondition(field.name, "any!", result)
    return DomainCondition(field.name, "in", result)


def _operator_child_of_domain(comodel: BaseModel, parent: str) -> Domain | OrderedSet:
    if comodel._parent_store and parent == comodel._parent_name:
        try:
            paths = comodel.mapped("parent_path")
        except MissingError:
            paths = comodel.exists().mapped("parent_path")
        return Domain.OR(
            DomainCondition("parent_path", "=like", path + "%") for path in paths
        )
    else:
        child_ids: OrderedSet[int] = OrderedSet()
        while comodel:
            child_ids.update(comodel._ids)
            query = comodel._search(
                DomainCondition(parent, "in", OrderedSet(comodel.ids))
            )
            comodel = comodel.browse(OrderedSet(query.get_result_ids()) - child_ids)
    return child_ids


def _operator_parent_of_domain(comodel: BaseModel, parent: str) -> OrderedSet:
    parent_ids: OrderedSet[int]
    if comodel._parent_store and parent == comodel._parent_name:
        try:
            paths = comodel.mapped("parent_path")
        except MissingError:
            paths = comodel.exists().mapped("parent_path")
        parent_ids = OrderedSet(
            int(label) for path in paths for label in path.split("/")[:-1]
        )
    else:
        parent_ids = OrderedSet()
        try:
            comodel.mapped(parent)
        except MissingError:
            comodel = comodel.exists()
        while comodel:
            parent_ids.update(comodel._ids)
            comodel = comodel[parent].filtered(lambda p: p.id not in parent_ids)
    return parent_ids


@operator_optimization(["any", "not any"], level=OptimizationLevel.FULL)
def _optimize_any_with_rights(condition, model):
    if model.env.su or condition._field(model).bypass_search_access:
        return DomainCondition(
            condition.field_expr, condition.operator + "!", condition.value
        )
    return condition


def _merge_set_conditions(
    cls: type[DomainNary], conditions: list[DomainCondition]
) -> list[DomainCondition]:
    assert all(isinstance(cond.value, OrderedSet) for cond in conditions)

    in_sets = [c.value for c in conditions if c.operator == "in"]
    not_in_sets = [c.value for c in conditions if c.operator == "not in"]

    def merged(operator: str, values: OrderedSet) -> list[DomainCondition]:
        values = OrderedSet(sorted(values, key=_nary_value_tiebreak))
        return [DomainCondition(conditions[0].field_expr, operator, values)]

    if cls.OPERATOR == "&":
        if in_sets:
            return merged("in", OrderedSet(intersection(in_sets) - union(not_in_sets)))
        else:
            return merged("not in", union(not_in_sets))
    elif not_in_sets:
        return merged("not in", OrderedSet(intersection(not_in_sets) - union(in_sets)))
    else:
        return merged("in", union(in_sets))


def intersection(sets: list[OrderedSet[typing.Any]]) -> OrderedSet[typing.Any]:
    return functools.reduce(operator.and_, sets)


def union(sets: list[OrderedSet[typing.Any]]) -> OrderedSet[typing.Any]:
    return OrderedSet(elem for s in sets for elem in s)


def _canonicalize_numeric_sets(
    conditions: list[DomainCondition], field_type: str
) -> list[DomainCondition]:
    result = []
    for condition in conditions:
        values = condition.value
        if not any(v.__class__ is str for v in values):
            result.append(condition)
            continue
        coerced = OrderedSet(
            v
            for v in (_coerce_numeric(v, field_type) for v in values)
            if v is not _NOT_A_NUMBER
        )
        result.append(
            DomainCondition(condition.field_expr, condition.operator, coerced)
        )
    return result


@nary_condition_optimization(operators=("in", "not in"))
def _optimize_merge_set_conditions_mono_value(cls: type[DomainNary], conditions, model):
    field = conditions[0]._field(model)
    if field.is_x2many or field.is_properties:
        return conditions
    if field.type in ("integer", "float", "monetary") and (
        field.name != "id" or model._auto
    ):
        conditions = _canonicalize_numeric_sets(conditions, field.type)
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(operators=("in",), field_types=["many2many", "one2many"])
def _optimize_merge_set_conditions_x2many_in(cls: type[DomainNary], conditions, model):
    if cls is DomainAnd:
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(
    operators=("not in",), field_types=["many2many", "one2many"]
)
def _optimize_merge_set_conditions_x2many_not_in(
    cls: type[DomainNary], conditions, model
):
    if cls is DomainOr:
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(["any"], ["many2one", "one2many", "many2many"])
@nary_condition_optimization(["any!"], ["many2one", "one2many", "many2many"])
def _optimize_merge_any(cls, conditions, model):
    field = conditions[0]._field(model)
    if not field.is_many2one and cls is DomainAnd:
        return conditions
    merge_conditions, other_conditions = partition(
        lambda c: isinstance(c.value, Domain), conditions
    )
    if len(merge_conditions) < 2:
        return conditions
    base = merge_conditions[0]
    sub_domain = cls(tuple(c.value for c in merge_conditions))
    return [
        DomainCondition(base.field_expr, base.operator, sub_domain),
        *other_conditions,
    ]


@nary_condition_optimization(["not any"], ["many2one", "one2many", "many2many"])
@nary_condition_optimization(["not any!"], ["many2one", "one2many", "many2many"])
def _optimize_merge_not_any(cls, conditions, model):
    field = conditions[0]._field(model)
    if not field.is_many2one and cls is DomainOr:
        return conditions
    merge_conditions, other_conditions = partition(
        lambda c: isinstance(c.value, Domain), conditions
    )
    if len(merge_conditions) < 2:
        return conditions
    base = merge_conditions[0]
    sub_domain = cls.INVERSE(tuple(c.value for c in merge_conditions))
    return [
        DomainCondition(base.field_expr, base.operator, sub_domain),
        *other_conditions,
    ]


@nary_optimization
def _optimize_same_conditions(cls, conditions, model):
    seen: set = set()
    for condition in conditions:
        if condition in seen:
            break
        seen.add(condition)
    else:
        return conditions

    seen.clear()
    kept = []
    for condition in conditions:
        if condition not in seen:
            seen.add(condition)
            kept.append(condition)
    return kept


__all__ = [
    "field_type_optimization",
    "intersection",
    "nary_condition_optimization",
    "nary_optimization",
    "operator_optimization",
    "union",
]
