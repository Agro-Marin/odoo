"""Domain optimization functions transforming and simplifying expressions.

Optimizations run at three levels: BASIC (transaction-independent: type
coercion, operator normalization), DYNAMIC_VALUES (may depend on dynamic values
like relative dates), and FULL (field search methods and record rules).

They are registered with the ``@operator_optimization`` (by operator),
``@field_type_optimization`` (by field type), ``@nary_optimization`` (n-ary
merging) and ``@nary_condition_optimization`` (condition merging) decorators.
"""

import functools
import logging
import operator
import typing
import warnings
from datetime import UTC, date, datetime, time, timedelta

from odoo.exceptions import MissingError
from odoo.libs.datetime import utc
from odoo.tools import SQL, OrderedSet, partition, str2bool
from odoo.tools.date_utils import parse_iso_date, resolve_date

from .._recordset import is_recordset
from ..primitives import COLLECTION_TYPES
from .ast import (
    _FALSE_DOMAIN,
    _MERGE_OPTIMIZATIONS,
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
    CONDITION_OPERATORS,
    INVERSE_OPERATOR,
    NEGATIVE_CONDITION_OPERATORS,
)

if typing.TYPE_CHECKING:
    from collections.abc import Collection

    from ..models import BaseModel

_logger = logging.getLogger("odoo.domains")


def operator_optimization(
    operators: Collection[str],
    level: OptimizationLevel = OptimizationLevel.BASIC,
) -> typing.Callable[[typing.Any], typing.Any]:
    """Register a condition operator optimization for (condition, model)."""
    assert operators, "Missing operator to register"
    CONDITION_OPERATORS.update(operators)

    def register(optimization: typing.Any) -> typing.Any:
        mapping = _OPTIMIZATIONS_FOR[level]
        for op in operators:
            mapping[op].append(optimization)
        return optimization

    return register


def field_type_optimization(
    field_types: Collection[str],
    level: OptimizationLevel = OptimizationLevel.BASIC,
) -> typing.Callable[[typing.Any], typing.Any]:
    """Register a condition optimization by field type for (condition, model)."""

    def register(optimization: typing.Any) -> typing.Any:
        mapping = _OPTIMIZATIONS_FOR[level]
        for field_type in field_types:
            mapping[field_type].append(optimization)
        return optimization

    return register


def nary_optimization(optimization: typing.Any) -> typing.Any:
    """Register a merge over the (optimized, sorted) children of an n-ary domain.

    Both AND and OR must be handled: optimizing ``a | b`` is optimizing
    ``~(~a & ~b)``, so implementations mirror the two cases, e.g.
    ``(optimize AND) if cond == cls.ZERO.value else (optimize OR)``. Children
    arrive optimized and sorted by (field, operator type, operator).
    """
    if not hasattr(optimization, "_match_operators"):
        optimization._match_operators = None
    _MERGE_OPTIMIZATIONS.append(optimization)
    return optimization


def nary_condition_optimization(
    operators: Collection[str], field_types: Collection[str] | None = None
) -> typing.Callable[[typing.Any], typing.Any]:
    """Register a merge over same-field condition children (via nary_optimization).

    The wrapped function receives a list of same-field conditions and returns
    optimized domains. To merge across operators, register for
    ``operator=CONDITION_OPERATORS`` and select the conditions to merge.
    """

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

        optimizer._match_operators = frozenset(operators)
        nary_optimization(optimizer)

        return optimization

    return register


@operator_optimization(["=?"])
def _operator_equal_if_value(condition, _):
    """a =? b  <=>  not b or a = b"""
    if not condition.value:
        return _TRUE_DOMAIN
    return DomainCondition(condition.field_expr, "=", condition.value)


@operator_optimization(["<>"])
def _operator_different(condition, _):
    """a <> b  =>  a != b"""
    warnings.warn(
        "Operator '<>' is deprecated since 19.0, use '!=' directly",
        DeprecationWarning,
        stacklevel=2,
    )
    return DomainCondition(condition.field_expr, "!=", condition.value)


@operator_optimization(["=="])
def _operator_equals(condition, _):
    """a == b  =>  a = b"""
    warnings.warn(
        "Operator '==' is deprecated since 19.0, use '=' directly",
        DeprecationWarning,
        stacklevel=2,
    )
    return DomainCondition(condition.field_expr, "=", condition.value)


@operator_optimization(["=", "!="])
def _operator_equal_as_in(condition, _):
    """Equality operators.

    Validation for some types and translate collection into 'in'.
    """
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
    """Make sure the value is an OrderedSet or use 'any' operator"""
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
    """Canonicalize every "no value" spelling to ``False`` in in/not-in sets.

    Two distinct aliases of NULL must collapse onto the single canonical
    ``False``, or the SQL and Python evaluators disagree and the set algebra
    below becomes unsound:

    ``None``
        The JSON/RPC spelling of a null comparand.
        :meth:`DomainCondition.checked` normalizes a *scalar* ``None`` to
        ``False``, but never looked inside a collection, so ``('a', 'in',
        [None])`` reached the evaluators unnormalized — and they disagreed:
        ``Field._condition_to_sql`` counts it as a null marker (``v is not
        False and v is not None``) and emits ``IS NULL``, while
        ``Field.filter_function`` tested only ``False`` / ``falsy_value``.
        ``search()`` therefore returned the NULL rows and
        ``filtered_domain()`` returned nothing for the same domain. Unlike
        ``falsy_value`` this holds for EVERY field type, so it is applied
        before (and independently of) the ``falsy_value`` check.

    a field's ``falsy_value``
        (``""`` for char/text/html, ``0`` for integer, ``0.0`` for
        float/monetary) SQL aliases it with NULL/False, but Python set algebra
        does not (``"" != False``). The n-ary set-merge
        (``_merge_set_conditions``) relies on set equality, so without this
        normalization ``a != "" | a != False`` would wrongly collapse to TRUE
        (and ``a = "" & a != False`` to a non-empty set).

    Canonicalizing here — rather than teaching each evaluator about ``None`` —
    keeps one spelling of null flowing downstream, so the set merges, the
    ``_optimize_in_required`` strip (which early-exits on ``False not in
    value``) and the query cache all see the same node.
    """
    value = condition.value
    if not isinstance(value, OrderedSet):
        return condition
    falsy = condition._field(model).falsy_value
    has_falsy_alias = falsy is not None and falsy is not False

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
    """Remove checks against a null value for required fields.

    Registered at FULL, not BASIC: it reads ``model._ids`` (depends on the
    record binding), and stripping ``False`` from a required NOT NULL field is
    valid only for persisted records — a new record may legitimately hold
    ``False`` in memory.

    That binding-dependence outlives this pass: the stripped node is stamped
    ``(FULL, model_name)`` like any other and may be retained (e.g. an
    ormcached record-rule domain) and later fed to ``_as_predicate`` over a
    recordset containing NewIds — a binding the ``all(model._ids)`` guard
    below never saw (NewId is always falsy, so any NewId in the binding
    disables the strip *at optimization time*; the trap is the caching).
    Since the strip destroys information (there is no form equivalent for
    both persisted and new records), the pre-strip condition is kept
    reachable on the result via the ``_predicate_fallback`` slot, which
    ``DomainCondition._as_predicate`` consults for NewId-containing
    recordsets.  Residual (documented, accepted) gaps: a strip-to-empty set
    collapses to the FALSE singleton in the next BASIC pass, and a later
    same-field set-merge builds a fresh node — both lose the fallback.
    """
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
    """Make sure the value is an optimized domain (or Query or SQL)"""
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
        condition._raise("Cannot use 'any' with non-relational fields")
    try:
        comodel = model.env[field.comodel_name]
    except KeyError:
        condition._raise("Cannot determine the comodel relation")
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


@operator_optimization([op for op in CONDITION_OPERATORS if op.endswith("like")])
def _optimize_like_str(condition, model):
    """Validate value for pattern matching, must be a str"""
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
        condition._raise("The pattern to match must be a string", error=TypeError)
    return DomainCondition(condition.field_expr, condition.operator, str(value))


@field_type_optimization(["many2one", "one2many", "many2many"])
def _optimize_relational_name_search(condition, model):
    """Search relational using `display_name`.

    When a relational field is compared to a string, we actually want to make
    a condition on the `display_name` field.
    Negative conditions are translated into a "not any" for consistency.
    """
    operator = condition.operator
    value = condition.value
    positive_operator = NEGATIVE_CONDITION_OPERATORS.get(operator, operator)
    any_operator = "any" if positive_operator == operator else "not any"
    if operator.endswith("like"):
        return DomainCondition(
            condition.field_expr,
            any_operator,
            DomainCondition("display_name", positive_operator, value),
        )
    if operator[0] in ("<", ">") and (
        isinstance(value, (str, bool, *COLLECTION_TYPES)) or is_recordset(value)
    ):
        condition._raise(
            "Inequality on a relational field is only supported against a "
            "single record id",
            error=TypeError,
        )
    if positive_operator != "in" or not isinstance(value, COLLECTION_TYPES):
        return condition
    if not any(isinstance(v, str) for v in value):
        return condition
    str_values, other_values = partition(lambda v: isinstance(v, str), value)
    domain = DomainCondition(
        condition.field_expr,
        any_operator,
        DomainCondition("display_name", positive_operator, str_values),
    )
    if other_values:
        if positive_operator == operator:
            domain |= DomainCondition(condition.field_expr, operator, other_values)
        else:
            domain &= DomainCondition(condition.field_expr, operator, other_values)
    return domain


_NOT_A_NUMBER = object()
"""Marker for a comparand that is not a number at all (see _coerce_numeric)."""


def _coerce_numeric(value: typing.Any, field_type: str) -> typing.Any:
    """Return a string *value* as an exact number, else :data:`_NOT_A_NUMBER`.

    Non-string values pass through untouched: ``bool`` means "unset"/"set" in a
    domain (never ``0``/``1``), and every other type is either already exact or
    the field's own conversion's business.  A fractional literal on an
    ``integer`` field stays exact (``'2.5'`` -> ``2.5``): the comparison is well
    defined (``2 < 2.5``, ``2 != 2.5``) and ``int()`` would both raise and, when
    it did not, move the boundary.
    """
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
    """Coerce a string comparand on a numeric field to its numeric value.

    Canonicalizing here — in the optimizer, once — is what keeps the domain's
    two evaluators in agreement.  ``Field.condition_to_sql`` used to coerce on
    its own (through ``convert_to_column`` / ``convert_to_cache``) while
    ``Field.filter_function`` compared the raw value, so the perfectly ordinary
    web-client / ``ir.filters`` shape ``('color', '=', '3')`` matched under
    ``search()`` and matched nothing under ``filtered_domain()``, and
    ``('color', '>', '3')`` raised ``TypeError`` in the Python evaluator only.

    This mirrors what ``_optimize_type_date`` / ``_optimize_type_datetime`` /
    ``_optimize_boolean_in`` already do for their field types.  ``False`` /
    ``None`` are left alone, since they mean "unset" and every operator branch
    handles them specially.

    A string is coerced with the field's own numeric type first
    (``int`` for ``integer``), then with ``float``: a fractional literal such as
    ``'2.5'`` used to reach ``int()`` inside ``convert_to_column`` and raise a
    bare ``ValueError`` -- a 500 on any user-supplied domain -- while the Python
    evaluator quietly matched nothing.  Both evaluators now compare the same
    ``2.5`` exactly (see ``Field._comparand_to_column``).

    A string that is not a number at all cannot be compared: for equality it
    simply matches nothing (``in`` → FALSE, ``not in`` → TRUE, which is also
    what the Python evaluator did on its own), while for an ordering comparison
    there is no meaningful answer, so it is rejected with a clear error in
    *both* evaluators instead of a bare ``int()`` ``ValueError`` in SQL only.
    """
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
        condition._raise(
            "Cannot compare the numeric field %r with a non-numeric value",
            condition.field_expr,
        )
    if coerced is value:
        return condition
    return DomainCondition(condition.field_expr, operator, coerced)


@field_type_optimization(["boolean"])
def _optimize_boolean_in(condition, model):
    """Coerce a boolean field's in/not-in set to bools (strings via ``str2bool``).

    ``b in [False]``  =>  ``b not in [True]``
    """
    value = condition.value
    operator = condition.operator
    if operator not in ("in", "not in"):
        condition._raise(
            "Operator %r is not supported on boolean field %r",
            operator,
            condition.field_expr,
        )
    if not isinstance(value, COLLECTION_TYPES):
        condition._raise(
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
    """b in [True, False]  =>  True"""
    if isinstance(condition.value, COLLECTION_TYPES) and set(condition.value) == {
        False,
        True,
    }:
        return Domain(condition.operator == "in")
    return condition


def _value_to_date(
    value: object,
    env: object,
    iso_only: bool = False,
) -> date | str | OrderedSet | SQL | typing.Literal[False] | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) or value is False:
        return value
    if isinstance(value, str):
        if iso_only:
            try:
                value = parse_iso_date(value)
            except ValueError:
                resolve_date(value, env)
                return value
        else:
            value = resolve_date(value, env)
        return _value_to_date(value, env)
    if isinstance(value, COLLECTION_TYPES):
        return OrderedSet(_value_to_date(v, env=env, iso_only=iso_only) for v in value)
    if isinstance(value, SQL):
        warnings.warn(
            "Since 19.0, use Domain.custom(to_sql=lambda model, alias, query: SQL(...))",
            DeprecationWarning,
            stacklevel=2,
        )
        return value
    raise ValueError(f"Failed to cast {value!r} into a date")


@operator_optimization([">", "<", ">=", "<="])
def _optimize_inequality_against_null(condition, model):
    """``field <op> False`` is an empty domain when the field has no falsy value.

    Fields that define a ``falsy_value`` (Char ``""``, Integer ``0``, Float
    ``0.0``) compare against that sentinel, so ``False`` is meaningful for them
    and this optimization does not apply. For the rest (Id, Date, Datetime,
    Selection, Binary, Many2one) an unset comparand is SQL NULL, and every
    ``x <op> NULL`` is NULL — i.e. matches nothing.

    Collapsing here, rather than in ``condition_to_sql`` / ``filter_function``,
    is what keeps the SQL and Python paths in agreement: it makes the node a
    plain boolean constant, so negation is handled by the domain algebra
    (``~_FALSE_DOMAIN`` is TRUE) instead of by SQL's three-valued ``NOT NULL``
    (which excludes every row) in one path and Python's two-valued ``not False``
    (which admits every row) in the other. ``_optimize_type_date`` has always
    done exactly this for dates; this generalizes it to every field with no
    falsy value.

    Without it, ``('id', '>', False)`` reached SQL as a bool parameter bound to
    an int4 column and raised ``UndefinedFunction: operator does not exist:
    integer > boolean``, aborting the transaction — on every model, since every
    model has ``id``.
    """
    value = condition.value
    if value is not False and value is not None:
        return condition
    if "." in condition.field_expr:
        return condition
    if condition._field(model).falsy_value is not None:
        return condition
    return _FALSE_DOMAIN


@field_type_optimization(["date"])
def _optimize_type_date(condition, model):
    """Make sure we have a date type in the value"""
    operator = condition.operator
    if (
        operator not in ("in", "not in", ">", "<", "<=", ">=")
        or "." in condition.field_expr
    ):
        return condition
    value = _value_to_date(condition.value, model.env, iso_only=True)
    if value is False and operator[0] in ("<", ">"):
        return _FALSE_DOMAIN
    return DomainCondition(condition.field_expr, operator, value)


@field_type_optimization(["date"], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_type_date_relative(condition, model):
    operator = condition.operator
    value = condition.value
    if (
        operator not in ("in", "not in", ">", "<", "<=", ">=")
        or "." in condition.field_expr
        or not isinstance(value, (str, OrderedSet))
        or (
            isinstance(value, OrderedSet) and not any(isinstance(v, str) for v in value)
        )
    ):
        return condition
    value = _value_to_date(value, model.env)
    return DomainCondition(condition.field_expr, operator, value)


def _value_to_datetime(
    value: object,
    env: object,
    iso_only: bool = False,
) -> tuple[datetime | str | OrderedSet | SQL | typing.Literal[False], bool]:
    """Convert value(s) to datetime.

    :return: ``(converted_value, all_dates)`` where *all_dates* flags that every
        input was a date (handled differently during rewrites).
    """
    if isinstance(value, datetime):
        if value.tzinfo:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value, False
    if value is False:
        return False, True
    if isinstance(value, str):
        if iso_only:
            try:
                value = parse_iso_date(value)
            except ValueError:
                _dt, is_date = _value_to_datetime(resolve_date(value, env), env)
                return value, is_date
        else:
            value = resolve_date(value, env)
        return _value_to_datetime(value, env)
    if isinstance(value, date):
        if value.year in (1, 9999):
            tz = None
        elif (tz := env.tz) == utc:
            tz = None
        value = datetime.combine(value, time.min, tz)
        if tz is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value, True
    if isinstance(value, COLLECTION_TYPES):
        if not value:
            return OrderedSet(), True
        value, is_date = zip(
            *(_value_to_datetime(v, env=env, iso_only=iso_only) for v in value),
            strict=False,
        )
        return OrderedSet(value), all(is_date)
    if isinstance(value, SQL):
        warnings.warn(
            "Since 19.0, use Domain.custom(to_sql=lambda model, alias, query: SQL(...))",
            DeprecationWarning,
            stacklevel=2,
        )
        return value, False
    raise ValueError(f"Failed to cast {value!r} into a datetime")


@field_type_optimization(["datetime"])
def _optimize_type_datetime(condition, model):
    """Make sure we have a datetime type in the value"""
    field_expr = condition.field_expr
    operator = condition.operator
    if operator not in ("in", "not in", ">", "<", "<=", ">=") or "." in field_expr:
        return condition
    value = condition.value
    if isinstance(value, COLLECTION_TYPES):
        pairs = [_value_to_datetime(v, model.env, iso_only=True) for v in value]
        value = OrderedSet(v for v, _is_date in pairs)
        dates = {v for v, is_date in pairs if is_date}
        is_date = False
    else:
        value, is_date = _value_to_datetime(value, model.env, iso_only=True)

    if operator[0] in ("<", ">"):
        if value is False:
            return _FALSE_DOMAIN
        if not isinstance(value, datetime):
            return condition
        if value.microsecond:
            assert not is_date, "date don't have microseconds"
            value = value.replace(microsecond=0)
        delta = timedelta(days=1) if is_date else timedelta(seconds=1)
        if operator == ">":
            try:
                value += delta
            except OverflowError:
                return _FALSE_DOMAIN
            operator = ">="
        elif operator == "<=":
            try:
                value += delta
            except OverflowError:
                return DomainCondition(field_expr, "!=", False)
            operator = "<"

    if (
        operator in ("in", "not in")
        and isinstance(value, COLLECTION_TYPES)
        and any(isinstance(v, datetime) for v in value)
    ):

        def equality_range(v: datetime) -> Domain:
            start = v.replace(microsecond=0)
            delta = timedelta(days=1) if v in dates else timedelta(seconds=1)
            try:
                end = start + delta
            except OverflowError:
                return DomainCondition(field_expr, ">=", start)
            return DomainCondition(field_expr, ">=", start) & DomainCondition(
                field_expr, "<", end
            )

        domain = DomainOr.apply(
            (
                equality_range(v)
                if isinstance(v, datetime)
                else DomainCondition(field_expr, "=", v)
            )
            for v in value
        )
        if operator == "not in":
            domain = ~domain
        return domain

    if operator == condition.operator and (
        value is condition.value
        or (value.__class__ is condition.value.__class__ and value == condition.value)
    ):
        return condition
    return DomainCondition(field_expr, operator, value)


@field_type_optimization(["datetime"], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_type_datetime_relative(condition, model):
    operator = condition.operator
    value = condition.value
    if (
        operator not in ("in", "not in", ">", "<", "<=", ">=")
        or "." in condition.field_expr
        or not isinstance(value, (str, OrderedSet))
        or (
            isinstance(value, OrderedSet) and not any(isinstance(v, str) for v in value)
        )
    ):
        return condition
    env = model.env

    def _resolve(v):
        return resolve_date(v, env) if isinstance(v, str) else v

    if isinstance(value, OrderedSet):
        resolved = OrderedSet(_resolve(v) for v in value)
    else:
        resolved = _resolve(value)
    return DomainCondition(condition.field_expr, operator, resolved)


@field_type_optimization(["properties"], level=OptimizationLevel.DYNAMIC_VALUES)
def _optimize_properties_date_datetime(condition, model):
    """Coerce relative/ISO date(time) values on a ``properties.<name>`` path.

    Property values are stored as ISO strings in jsonb, so a relative value such
    as ``"today"`` (or any date string) must be resolved to a concrete date and
    re-serialized as a string.  Without this, the comparison runs
    lexicographically against the raw ``"today"`` literal, which matches every or
    no row (upstream ``4a754c7b31f``; dropped in the fork's domain refactor).
    """
    operator = condition.operator
    if (
        operator not in ("in", "not in", ">", "<", "<=", ">=")
        or condition.field_expr.count(".") != 1
        or not isinstance(condition.value, (str, OrderedSet))
    ):
        return condition
    definition = model.get_property_definition(condition.field_expr)
    property_type = definition.get("type")

    if property_type == "date":
        value = _value_to_date(condition.value, model.env)
    elif property_type == "datetime":
        value, _ = _value_to_datetime(condition.value, model.env)
    else:
        return condition
    if isinstance(value, COLLECTION_TYPES):
        value = OrderedSet(
            str(item) if isinstance(item, (date, datetime)) else item for item in value
        )
    elif isinstance(value, (date, datetime)):
        value = str(value)

    return DomainCondition(condition.field_expr, operator, value)


@field_type_optimization(["binary"])
def _optimize_type_binary_attachment(condition, model):
    field = condition._field(model)
    operator = condition.operator
    value = condition.value
    if field.attachment and not (
        operator in ("in", "not in") and set(value) == {False}
    ):
        try:
            condition._raise(
                "Binary field stored in attachment, accepts only existence check; skipping domain"
            )
        except ValueError:
            _logger.exception("Invalid operator for a binary field")
        return _TRUE_DOMAIN
    if operator.endswith("like"):
        condition._raise(
            "Cannot use like operators with binary fields",
            error=NotImplementedError,
        )
    return condition


@operator_optimization(["parent_of", "child_of"], OptimizationLevel.FULL)
def _operator_hierarchy(condition, model):
    """Transform a hierarchy operator ``(field, operator, value)`` into a domain.

    *field* is 'id' (default ``_parent_name`` relation) or a field whose comodel
    equals the model. *value* (ids, a name to search, etc.) seeds the set of
    records, then the relation is followed up for ``parent_of`` / down for
    ``child_of``. The result keys on 'id' for an 'id' or many2one field; when the
    comodel differs from the model it is ``('field', 'any', ('id', op, value))``.
    """
    if condition.operator == "parent_of":
        hierarchy = _operator_parent_of_domain
    else:
        hierarchy = _operator_child_of_domain
    value = condition.value
    if value is False:
        return _FALSE_DOMAIN
    if value is True:
        condition._raise("True is not a valid hierarchy value")
    field = condition._field(model)
    if field.type == "many2one":
        comodel = model.env[field.comodel_name].with_context(active_test=False)
    elif field.type in ("one2many", "many2many"):
        comodel = model.env[field.comodel_name].with_context(**field.context)
    elif field.name == "id":
        comodel = model
    else:
        condition._raise(
            f"Cannot execute {condition.operator} for {field}, works only for relational fields"
        )
    comodel_sudo = comodel.sudo().with_context(active_test=False)
    parent = comodel._parent_name
    if comodel._name == model._name:
        if condition.field_expr != "id":
            parent = condition.field_expr
        if field.type == "many2one":
            field = model._fields["id"]
    if isinstance(value, (int, str)):
        value = [value]
    elif not isinstance(value, COLLECTION_TYPES):
        condition._raise(f"Value of type {type(value)} is not supported")
    if any(isinstance(v, bool) for v in value):
        if any(v is True for v in value):
            condition._raise("True is not a valid hierarchy value")
        value = [v for v in value if v is not False]
    coids, other_values = partition(lambda v: isinstance(v, int), value)
    search_domain = _FALSE_DOMAIN
    if field.type == "many2many":
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
    """Return a domain or id set matching all children of *comodel*."""
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
    """Return the id set of all parents of *comodel*."""
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


@field_type_optimization(["many2one"], level=OptimizationLevel.FULL)
def _optimize_m2o_bypass_comodel_id_lookup(condition, model):
    """Avoid comodel's subquery, if it can be compared with the field directly"""
    operator = condition.operator
    if (
        operator in ("any!", "not any!")
        and isinstance(subdomain := condition.value, DomainCondition)
        and subdomain.field_expr == "id"
        and (suboperator := subdomain.operator) in ("in", "not in", "any!", "not any!")
    ):
        val = subdomain.value
        match suboperator:
            case "in":
                domain = DomainCondition(condition.field_expr, "in", val - {False})
            case "not in":
                domain = DomainCondition(condition.field_expr, "not in", val | {False})
            case "any!":
                domain = DomainCondition(condition.field_expr, "any!", val)
            case "not any!":
                domain = DomainCondition(
                    condition.field_expr, "!=", False
                ) & DomainCondition(condition.field_expr, "not any!", val)
        if operator == "not any!":
            domain = ~domain
        return domain

    return condition


def _merge_set_conditions(
    cls: type[DomainNary], conditions: list[DomainCondition]
) -> list[DomainCondition]:
    """Merge 'in'/'not in' conditions on one field into a single value set.

    E.g. ``a in {1} or a in {2}`` -> ``a in {1, 2}``;
    ``a in {1, 2} and a not in {2, 5}`` -> ``a in {1}``.

    The merged set is emitted in canonical element order (the
    :func:`~odoo.orm.domain.ast._nary_value_tiebreak` ranking): the element
    order of an OrderedSet does not change the SQL of the flat leaf itself
    (single bound parameter), but it leaks into the ordering of *sibling
    subtrees* through the repr-based ``_nary_subtree_tiebreak``, so without
    sorting, two semantically identical domains written in different leaf order
    optimized to different (``!=``) trees with different SQL text.  Only merged
    sets are canonicalized here; unmerged user-supplied sets keep their order
    (it is semantically irrelevant, and rewriting them would churn every
    domain).
    """
    assert all(isinstance(cond.value, OrderedSet) for cond in conditions)

    in_sets = [c.value for c in conditions if c.operator == "in"]
    not_in_sets = [c.value for c in conditions if c.operator == "not in"]

    def merged(operator: str, values: OrderedSet) -> list[DomainCondition]:
        values = OrderedSet(sorted(values, key=_nary_value_tiebreak))
        return [DomainCondition(conditions[0].field_expr, operator, values)]

    if cls.OPERATOR == "&":
        if in_sets:
            return merged("in", intersection(in_sets) - union(not_in_sets))
        else:
            return merged("not in", union(not_in_sets))
    elif not_in_sets:
        return merged("not in", intersection(not_in_sets) - union(in_sets))
    else:
        return merged("in", union(in_sets))


def intersection(sets: list[OrderedSet[typing.Any]]) -> OrderedSet[typing.Any]:
    """Intersection of a list of OrderedSets."""
    return functools.reduce(operator.and_, sets)


def union(sets: list[OrderedSet[typing.Any]]) -> OrderedSet[typing.Any]:
    """Union of a list of OrderedSets."""
    return OrderedSet(elem for s in sets for elem in s)


def _canonicalize_numeric_sets(
    conditions: list[DomainCondition], field_type: str
) -> list[DomainCondition]:
    """Coerce string elements of ``in``/``not in`` value sets to numbers.

    Merging combines the sets by element *identity*, so a string element never
    meets its numeric twin: ``{216, 217} & {'217'}`` is empty and
    ``('id', 'in', ids) & ('id', 'in', ['217'])`` collapsed the whole domain to
    FALSE in SQL -- while each condition *alone* selects record 217 in both
    evaluators (``condition_to_sql`` converts the comparand, and so does
    ``Id.filter_function``).

    ``_optimize_numeric_comparand`` cannot do this for ``id``: every prefetch
    optimizes ``('id', 'in', ids)`` over a machine-built int collection, and
    scanning it there measured +46% on ``optimize_full``.  Here the scan is free
    where it mattered -- a merge needs *two* conditions on the same field, which
    the prefetch domain never has.

    An element that is not a number at all is dropped: no numeric column value
    can equal it, so it constrains nothing in either direction (``in`` narrows,
    ``not in`` excludes nothing).
    """
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
    """Merge 'in'/'not in' conditions; skip x2many (different semantics)."""
    field = conditions[0]._field(model)
    if field.type in ("many2many", "one2many", "properties"):
        return conditions
    if field.type in ("integer", "float", "monetary") and (
        field.name != "id" or model._auto
    ):
        conditions = _canonicalize_numeric_sets(conditions, field.type)
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(operators=("in",), field_types=["many2many", "one2many"])
def _optimize_merge_set_conditions_x2many_in(cls: type[DomainNary], conditions, model):
    """Merge x2many 'in' conditions, as for the 'any' operator."""
    if cls is DomainAnd:
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(
    operators=("not in",), field_types=["many2many", "one2many"]
)
def _optimize_merge_set_conditions_x2many_not_in(
    cls: type[DomainNary], conditions, model
):
    """Merge x2many 'not in' conditions, as for the 'not any' operator."""
    if cls is DomainOr:
        return conditions
    return _merge_set_conditions(cls, conditions)


@nary_condition_optimization(["any"], ["many2one", "one2many", "many2many"])
@nary_condition_optimization(["any!"], ["many2one", "one2many", "many2many"])
def _optimize_merge_any(cls, conditions, model):
    """Merge 'any' conditions on relational fields into fewer sub-queries.

    ``a any (f=8) or a any (g=5)`` -> ``a any (f=8 or g=5)`` (all fields);
    ``a any (f=8) and a any (g=5)`` -> ``a any (f=8 and g=5)`` (many2one only).
    """
    field = conditions[0]._field(model)
    if field.type != "many2one" and cls is DomainAnd:
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
    """Merge 'not any' conditions on relational fields into fewer sub-queries.

    ``a not any (f=1) or a not any (g=5)`` -> ``a not any (f=1 and g=5)``
    (many2one only); the ``and`` form -> ``a not any (f=1 or g=5)`` (all fields).
    """
    field = conditions[0]._field(model)
    if field.type != "many2one" and cls is DomainOr:
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
    """Remove duplicate conditions, regardless of their position.

    De-duplicating only *adjacent* equals (the previous behaviour) is not
    confluent: the n-ary sort key excludes the condition value, so two equal
    conditions sharing a sort key need not end up adjacent, and operators
    without a value-merge pass (``like``, ``ilike``, …) would then survive in
    one permutation but not the other — the same logical domain optimizing to
    two different SQL strings, defeating the query cache.  A first-occurrence
    set de-dup is order-independent and O(n); every possible child is hashable
    (``DomainCondition.__hash__`` is total, falling back to a value-independent
    hash for unhashable SQL/Query values).
    """
    seen: set = set()
    for condition in conditions:
        if condition in seen:
            break
        seen.add(condition)
    else:
        return conditions

    seen.clear()
    return [c for c in conditions if not (c in seen or seen.add(c))]


__all__ = [
    "field_type_optimization",
    "intersection",
    "nary_condition_optimization",
    "nary_optimization",
    "operator_optimization",
    "union",
]
