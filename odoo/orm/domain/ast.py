import collections
import contextlib
import datetime
import decimal
import enum
import functools
import itertools
import logging
import operator
import types
import typing
import warnings

from odoo.exceptions import UserError
from odoo.tools import SQL, OrderedSet, Query, classproperty

from .._recordset import is_recordset
from ..parsing import parse_field_expr
from ..primitives import COLLECTION_TYPES, NewId
from .constants import (
    CONDITION_OPERATORS,
    FALSE_LEAF,
    INTERNAL_CONDITION_OPERATORS,
    INVERSE_INEQUALITY,
    INVERSE_OPERATOR,
    NEGATIVE_CONDITION_OPERATORS,
    STANDARD_CONDITION_OPERATORS,
    SUBDOMAIN_OPERATORS,
    TRUE_LEAF,
)

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ..fields import Field
    from ..models import BaseModel

    M = typing.TypeVar("M", bound=BaseModel)

_logger = logging.getLogger("odoo.domains")


class OptimizationLevel(enum.IntEnum):
    NONE = 0
    BASIC = enum.auto()
    DYNAMIC_VALUES = enum.auto()
    FULL = enum.auto()

    @functools.cached_property
    def next_level(self) -> OptimizationLevel:
        if self is OptimizationLevel.FULL:
            raise ValueError("FULL level is the last one")
        return OptimizationLevel(int(self) + 1)


MAX_OPTIMIZE_ITERATIONS = 1000

MAX_DOMAIN_NESTING = 100
"""Maximum AST operator-nesting depth accepted when parsing a domain list.

Domain traversal is recursive, so a pathologically deep (e.g. attacker-supplied)
domain blows the stack with an opaque ``RecursionError`` mid-evaluation; we
reject it at parse time with a clear ``ValueError`` instead. Real domains nest a
handful of levels, so 100 is well beyond legitimate use yet safely below the
interpreter recursion limit.
"""


def _comparand_eq(left: typing.Any, right: typing.Any) -> bool:
    if left.__class__ in (list, tuple, set, frozenset, OrderedSet):
        if len(left) != len(right):
            return False
        try:
            return {(type(v), v) for v in left} == {(type(v), v) for v in right}
        except TypeError:
            return left == right
    return left == right


def _iter_subdomains(node: Domain) -> typing.Iterator[Domain]:
    if isinstance(node, DomainNary):
        yield from node.children
    elif isinstance(node, DomainNot):
        yield node.child


@contextlib.contextmanager
def _recursion_error_as_value_error():
    try:
        yield
    except RecursionError:
        raise ValueError(
            "Domain nesting too deep to optimize: combined n-ary and 'any' "
            "nesting exhausts the evaluation stack"
        ) from None


def _check_domain_nesting(domain: Domain, max_depth: int) -> None:
    stack: list[tuple[Domain, int]] = [(domain, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            raise ValueError(
                f"Domain nesting too deep (>{max_depth} levels); refusing to "
                f"build it to avoid a RecursionError during evaluation"
            )
        stack.extend((child, depth + 1) for child in _iter_subdomains(node))


def _check_subdomain_nesting(value: object, max_depth: int) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            raise ValueError(
                f"Domain nesting too deep (>{max_depth} levels); refusing to "
                f"build it to avoid a RecursionError during evaluation"
            )
        if not isinstance(node, (list, tuple)):
            continue
        child_depth = depth + 1
        stack.extend(
            (item[2], child_depth)
            for item in node
            if isinstance(item, (list, tuple))
            and len(item) == 3
            and isinstance(item[1], str)
            and item[1].lower() in SUBDOMAIN_OPERATORS
            and isinstance(item[2], (list, tuple))
        )


if typing.TYPE_CHECKING:
    ConditionOptimization = Callable[["DomainCondition", "BaseModel"], "Domain"]
    MergeOptimization = Callable[
        [type["DomainNary"], list["Domain"], "BaseModel"], list["Domain"]
    ]

_OPTIMIZATIONS_FOR: dict[OptimizationLevel, dict[str, list]] = {
    level: collections.defaultdict(list)
    for level in OptimizationLevel
    if level != OptimizationLevel.NONE
}
_MERGE_OPTIMIZATIONS: list = []


_CONSTANT_TIEBREAK: tuple[int, typing.Any] = (2, "")


def _nary_value_tiebreak(value: typing.Any) -> tuple[int, typing.Any]:
    if isinstance(value, str):
        return (0, value)
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, datetime.datetime):
        return (3, value)
    if isinstance(value, datetime.date):
        return (4, value)
    if isinstance(value, decimal.Decimal):
        return (5, value)
    return _CONSTANT_TIEBREAK


def _nary_subtree_tiebreak(domain: Domain) -> tuple[int, typing.Any]:
    return (2, repr(list(domain)))


def _optimize_nary_sort_key(
    domain: Domain,
) -> tuple[str, str, str, tuple[int, typing.Any]]:
    if isinstance(domain, DomainCondition):
        op = domain.operator
        positive_op = NEGATIVE_CONDITION_OPERATORS.get(op, op)
        if positive_op == "in":
            order = "0in"
        elif positive_op == "any":
            order = "1any"
        elif positive_op == "any!":
            order = "2any"
        elif positive_op.endswith("like"):
            order = "like"
        else:
            order = positive_op
        return domain.field_expr, order, op, _nary_value_tiebreak(domain.value)
    elif hasattr(domain, "OPERATOR") and isinstance(domain.OPERATOR, str):
        return "~", "", domain.OPERATOR, _nary_subtree_tiebreak(domain)
    else:
        return "~", "~", domain.__class__.__name__, _nary_subtree_tiebreak(domain)


class Domain:
    __slots__ = ("_opt",)
    _opt: tuple[OptimizationLevel, str | None]

    @property
    def _opt_level(self) -> OptimizationLevel:
        return self._opt[0]

    @property
    def _opt_model_name(self) -> str | None:
        return self._opt[1]

    # PYI034 wants `Self` here, but `Domain(...)` genuinely returns a DIFFERENT
    # class than `cls` — a bare field expr builds a DomainCondition, a bool builds
    # a DomainBool. `Self` would be a lie and costs 9 mypy [return-value] errors.
    def __new__(cls, *args: object, internal: bool = False) -> Domain:  # noqa: PYI034  see comment above
        if len(args) > 1:
            if isinstance(args[0], str):
                return DomainCondition(*args).checked()
            if args == TRUE_LEAF:
                return _TRUE_DOMAIN
            if args == FALSE_LEAF:
                return _FALSE_DOMAIN
            raise TypeError(f"Domain() invalid arguments: {args!r}")

        arg = args[0]
        if isinstance(arg, Domain):
            return arg
        if arg is True or arg in ([], ()):
            return _TRUE_DOMAIN
        if arg is False:
            return _FALSE_DOMAIN
        if arg is NotImplemented:
            raise NotImplementedError

        if not isinstance(arg, (list, tuple)):
            raise TypeError(f"Domain() invalid argument type for domain: {arg!r}")
        if internal:
            _check_subdomain_nesting(arg, MAX_DOMAIN_NESTING)
        if len(arg) == 1:
            item = arg[0]
            if isinstance(item, (tuple, list)) and len(item) == 3:
                if not isinstance(item[1], str):
                    raise ValueError(f"Domain() invalid item in domain: {item!r}")
                op = item[1].lower()
                if internal:
                    if op in SUBDOMAIN_OPERATORS and isinstance(item[2], (list, tuple)):
                        item = (
                            item[0],
                            item[1],
                            Domain(item[2], internal=True),
                        )
                elif op in INTERNAL_CONDITION_OPERATORS:
                    raise ValueError(f"Domain() invalid item in domain: {item!r}")
                return Domain(*item)
            if isinstance(item, Domain):
                return item
        stack: list[Domain] = []
        try:
            for item in reversed(arg):
                if isinstance(item, (tuple, list)) and len(item) == 3:
                    if not isinstance(item[1], str):
                        raise ValueError(f"Domain() invalid item in domain: {item!r}")
                    op = item[1].lower()
                    if internal:
                        if op in SUBDOMAIN_OPERATORS and isinstance(
                            item[2], (list, tuple)
                        ):
                            item = (
                                item[0],
                                item[1],
                                Domain(item[2], internal=True),
                            )
                    elif op in INTERNAL_CONDITION_OPERATORS:
                        raise ValueError(f"Domain() invalid item in domain: {item!r}")
                    stack.append(Domain(*item))
                elif item == DomainAnd.OPERATOR:
                    stack.append(stack.pop() & stack.pop())
                elif item == DomainOr.OPERATOR:
                    stack.append(stack.pop() | stack.pop())
                elif item == DomainNot.OPERATOR:
                    stack.append(~stack.pop())
                elif isinstance(item, Domain):
                    stack.append(item)
                else:
                    raise ValueError(f"Domain() invalid item in domain: {item!r}")
            if len(stack) == 1:
                result = stack[0]
            else:
                result = Domain.AND(reversed(stack))
        except IndexError:
            raise ValueError(f"Domain() malformed domain {arg!r}") from None
        _check_domain_nesting(result, MAX_DOMAIN_NESTING)
        return result

    @classproperty
    def TRUE(self) -> Domain:
        return _TRUE_DOMAIN

    @classproperty
    def FALSE(self) -> Domain:
        return _FALSE_DOMAIN

    NEGATIVE_OPERATORS = types.MappingProxyType(NEGATIVE_CONDITION_OPERATORS)

    @staticmethod
    def custom(
        *,
        to_sql: Callable[[BaseModel, str, Query], SQL],
        predicate: Callable[[BaseModel], bool] | None = None,
    ) -> DomainCustom:
        return DomainCustom(to_sql, predicate)

    @staticmethod
    def AND(items: Iterable[object]) -> Domain:
        return DomainAnd.apply(Domain(item) for item in items)

    @staticmethod
    def OR(items: Iterable[object]) -> Domain:
        return DomainOr.apply(Domain(item) for item in items)

    def __setattr__(self, name: str, value: object) -> None:
        msg = "Domain objects are immutable"
        raise TypeError(msg)

    def __delattr__(self, name: str) -> None:
        msg = "Domain objects are immutable"
        raise TypeError(msg)

    def __and__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, Domain):
            if isinstance(other, DomainBool):
                return self if other.value else other
            return DomainAnd.apply([self, other])
        return NotImplemented

    def __or__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, Domain):
            if isinstance(other, DomainBool):
                return other if other.value else self
            return DomainOr.apply([self, other])
        return NotImplemented

    def __invert__(self) -> Domain:
        return DomainNot(self)

    def _negate(self, model: BaseModel) -> Domain:
        return ~self

    def __add__(self, other: object) -> Domain | list[object]:
        if isinstance(other, Domain):
            warnings.warn(
                "Domain + Domain is deprecated, use Domain & Domain (AND) "
                "or Domain | Domain (OR) instead",
                DeprecationWarning,
                stacklevel=2,
            )
            return self & other
        if not isinstance(other, list):
            msg = "Domain() can concatenate only lists"
            raise TypeError(msg)
        warnings.warn(
            "Domain + list is deprecated, convert the list to a Domain first",
            DeprecationWarning,
            stacklevel=2,
        )
        return list(self) + other

    def __radd__(self, other: list[object]) -> list[object]:
        warnings.warn(
            "list + Domain is deprecated, convert the list to a Domain first",
            DeprecationWarning,
            stacklevel=2,
        )
        return other + list(self)

    def __bool__(self) -> bool:
        return not self.is_true()

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError

    def __iter__(self) -> typing.Iterator[object]:
        yield from ()
        raise NotImplementedError

    def __reversed__(self) -> typing.Iterator[object]:
        return reversed(list(self))

    def __repr__(self) -> str:
        return repr(list(self))

    def is_true(self) -> bool:
        return False

    def is_false(self) -> bool:
        return False

    def iter_conditions(self) -> typing.Iterator[DomainCondition]:
        yield from ()

    def map_conditions(self, function: Callable[[DomainCondition], Domain]) -> Domain:
        return self

    def validate(self, model: BaseModel) -> None:
        with _recursion_error_as_value_error():
            self._optimize(model, OptimizationLevel.FULL)

    def _as_predicate(self, records: M) -> Callable[[M], bool]:
        raise NotImplementedError

    def _predicate_optimized(self, records: BaseModel) -> Domain | None:
        if self._opt_level >= OptimizationLevel.DYNAMIC_VALUES:
            return None
        with _recursion_error_as_value_error():
            return self._optimize(records, OptimizationLevel.DYNAMIC_VALUES)

    def optimize(self, model: BaseModel) -> Domain:
        with _recursion_error_as_value_error():
            return self._optimize(model, OptimizationLevel.BASIC)

    def optimize_full(self, model: BaseModel) -> Domain:
        with _recursion_error_as_value_error():
            return self._optimize(model, OptimizationLevel.FULL)

    @typing.final
    def _optimize(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        model_name = model._name
        opt_level, opt_model = self._opt
        if opt_model == model_name and opt_level >= level:
            return self
        if opt_model is not None and opt_model != model_name:
            domain = self._reset_opt_copy()
        else:
            domain = self
        count = 0
        while domain._opt[0] < level:
            if (count := count + 1) > MAX_OPTIMIZE_ITERATIONS:
                msg = "Domain.optimize: too many loops"
                raise RecursionError(msg)
            next_level = domain._opt[0].next_level
            previous, domain = domain, domain._optimize_step(model, next_level)
            if domain == previous and domain._opt[0] < next_level:
                object.__setattr__(domain, "_opt", (next_level, model_name))
        return domain

    def _reset_opt_copy(self) -> Domain:
        missing = object()
        clone = object.__new__(type(self))
        for klass in type(self).__mro__:
            for slot in getattr(klass, "__slots__", ()):
                if slot in ("_opt", "_field_instance"):
                    continue
                value = getattr(self, slot, missing)
                if value is not missing:
                    object.__setattr__(clone, slot, value)
        object.__setattr__(clone, "_opt", (OptimizationLevel.NONE, None))
        if hasattr(self, "_field_instance"):
            object.__setattr__(clone, "_field_instance", None)
        return clone

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        return self

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        raise NotImplementedError


class DomainBool(Domain):
    __slots__ = ("value",)
    value: bool

    _SQL_TRUE = SQL("TRUE")
    _SQL_FALSE = SQL("FALSE")

    def __new__(cls, value: bool):
        self = object.__new__(cls)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "_opt", (OptimizationLevel.FULL, None))
        return self

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return hash(self.value)

    def is_true(self) -> bool:
        return self.value

    def is_false(self) -> bool:
        return not self.value

    def __invert__(self) -> DomainBool:
        return _FALSE_DOMAIN if self.value else _TRUE_DOMAIN

    def __and__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, Domain):
            return other if self.value else self
        return NotImplemented

    def __or__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, Domain):
            return self if self.value else other
        return NotImplemented

    def __iter__(self) -> typing.Iterator[tuple[int, str, int]]:
        yield TRUE_LEAF if self.value else FALSE_LEAF

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        return lambda _: self.value

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        return self._SQL_TRUE if self.value else self._SQL_FALSE


_TRUE_DOMAIN = DomainBool(True)
_FALSE_DOMAIN = DomainBool(False)


class DomainNot(Domain):
    OPERATOR = "!"

    __slots__ = ("child",)
    child: Domain

    def __new__(cls, child: Domain):
        self = object.__new__(cls)
        object.__setattr__(self, "child", child)
        object.__setattr__(self, "_opt", (OptimizationLevel.NONE, None))
        return self

    def __invert__(self) -> Domain:
        return self.child

    def __iter__(self) -> typing.Iterator[object]:
        yield self.OPERATOR
        yield from self.child

    def iter_conditions(self) -> typing.Iterator[DomainCondition]:
        yield from self.child.iter_conditions()

    def map_conditions(self, function: Callable[[DomainCondition], Domain]) -> Domain:
        return ~(self.child.map_conditions(function))

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        return self.child._optimize(model, level)._negate(model)

    def __eq__(self, other: object) -> bool:
        return self is other or (
            isinstance(other, DomainNot) and self.child == other.child
        )

    def __hash__(self) -> int:
        return ~hash(self.child)

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        predicate = self.child._as_predicate(records)
        return lambda rec: not predicate(rec)

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        condition = self.child._to_sql(model, alias, query)
        return SQL("(%s) IS NOT TRUE", condition)


class DomainNary(Domain):
    OPERATOR: str
    OPERATOR_SQL: SQL = SQL(" ??? ")
    ZERO: DomainBool = _FALSE_DOMAIN

    __slots__ = ("children",)
    children: tuple[Domain, ...]

    def __new__(cls, children: tuple[Domain, ...]):
        if len(children) < 2:
            raise ValueError(
                f"DomainNary requires at least 2 children, got {len(children)}"
            )
        self = object.__new__(cls)
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "_opt", (OptimizationLevel.NONE, None))
        return self

    @classmethod
    def apply(cls, items: Iterable[Domain]) -> Domain:
        children = cls._flatten(items)
        if len(children) == 1:
            return children[0]
        return cls(tuple(children))

    @classmethod
    def _flatten(cls, children: Iterable[Domain]) -> list[Domain]:
        result: list[Domain] = []
        for child in children:
            if isinstance(child, DomainBool):
                if child != cls.ZERO:
                    return [child]
            elif isinstance(child, cls):
                result.extend(child.children)
            else:
                result.append(child)
        return result or [cls.ZERO]

    def __iter__(self) -> typing.Iterator[object]:
        yield from itertools.repeat(self.OPERATOR, len(self.children) - 1)
        for child in self.children:
            yield from child

    def __eq__(self, other: object) -> bool:
        return self is other or (
            isinstance(other, DomainNary)
            and self.OPERATOR == other.OPERATOR
            and self.children == other.children
        )

    def __hash__(self) -> int:
        return hash(self.OPERATOR) ^ hash(self.children)

    @classproperty
    def INVERSE(self) -> type[DomainNary]:
        raise NotImplementedError

    def __invert__(self) -> DomainNary:
        return self.INVERSE(tuple(~child for child in self.children))

    def _negate(self, model: BaseModel) -> DomainNary:
        return self.INVERSE(tuple(child._negate(model) for child in self.children))

    def iter_conditions(self) -> typing.Iterator[DomainCondition]:
        for child in self.children:
            yield from child.iter_conditions()

    def map_conditions(self, function: Callable[[DomainCondition], Domain]) -> Domain:
        return self.apply(child.map_conditions(function) for child in self.children)

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        children = self._flatten(
            child._optimize(model, level) for child in self.children
        )
        if len(children) > 1:
            children.sort(key=_optimize_nary_sort_key)
            cls = type(self)
            present_ops = {
                c.operator for c in children if isinstance(c, DomainCondition)
            }
            for merge in _MERGE_OPTIMIZATIONS:
                gate = merge._match_operators
                if gate is not None and gate.isdisjoint(present_ops):
                    continue
                children = merge(cls, children, model)
            if len(self.children) == len(children) and all(
                map(operator.is_, self.children, children, strict=True)
            ):
                return self
        return self.apply(children)

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        return SQL(
            "(%s)",
            self.OPERATOR_SQL.join(
                c._to_sql(model, alias, query) for c in self.children
            ),
        )


class DomainAnd(DomainNary):
    __slots__ = ()
    OPERATOR = "&"
    OPERATOR_SQL = SQL(" AND ")
    ZERO = _TRUE_DOMAIN

    @classproperty
    def INVERSE(self) -> type[DomainNary]:
        return DomainOr

    def __and__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, DomainAnd):
            return DomainAnd(self.children + other.children)
        return super().__and__(other)

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        if (optimized := self._predicate_optimized(records)) is not None:
            return optimized._as_predicate(records)
        predicates = tuple(child._as_predicate(records) for child in self.children)

        def and_predicate(record: BaseModel) -> bool:
            return all(pred(record) for pred in predicates)

        return and_predicate


class DomainOr(DomainNary):
    __slots__ = ()
    OPERATOR = "|"
    OPERATOR_SQL = SQL(" OR ")
    ZERO = _FALSE_DOMAIN

    @classproperty
    def INVERSE(self) -> type[DomainNary]:
        return DomainAnd

    def __or__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, DomainOr):
            return DomainOr(self.children + other.children)
        return super().__or__(other)

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        if (optimized := self._predicate_optimized(records)) is not None:
            return optimized._as_predicate(records)
        predicates = tuple(child._as_predicate(records) for child in self.children)

        def or_predicate(record: BaseModel) -> bool:
            return any(pred(record) for pred in predicates)

        return or_predicate


class DomainCustom(Domain):
    __slots__ = ("_filtered", "_sql")

    _filtered: Callable[[BaseModel], bool] | None
    _sql: Callable[[BaseModel, str, Query], SQL]

    def __new__(
        cls,
        sql: Callable[[BaseModel, str, Query], SQL],
        filtered: Callable[[BaseModel], bool] | None = None,
    ):
        self = object.__new__(cls)
        object.__setattr__(self, "_sql", sql)
        object.__setattr__(self, "_filtered", filtered)
        object.__setattr__(self, "_opt", (OptimizationLevel.FULL, None))
        return self

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        if self._filtered is not None:
            return self._filtered
        query = records._search(
            DomainCondition("id", "in", records.ids) & self, order="id"
        )
        return DomainCondition("id", "any", query)._as_predicate(records)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, DomainCustom)
            and self._sql == other._sql
            and self._filtered == other._filtered
        )

    def __hash__(self) -> int:
        return hash(self._sql) ^ hash(self._filtered)

    def __iter__(self) -> typing.Iterator[object]:
        yield ("<custom_sql>", "", "")

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        return self._sql(model, alias, query)


class DomainCondition(Domain):
    __slots__ = (
        "_field_instance",
        "_hash",
        "_predicate_fallback",
        "field_expr",
        "operator",
        "value",
    )
    _field_instance: Field | None
    field_expr: str
    operator: str
    value: typing.Any

    def __new__(cls, field_expr: str, operator: str, value: object) -> DomainCondition:  # noqa: PYI034  see Domain.__new__
        self = object.__new__(cls)
        object.__setattr__(self, "field_expr", field_expr)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "_field_instance", None)
        object.__setattr__(self, "_opt", (OptimizationLevel.NONE, None))
        return self

    def checked(self) -> DomainCondition:
        if not isinstance(self.field_expr, str) or not self.field_expr:
            self._raise("Empty field name", error=TypeError)
        op = self.operator.lower()
        if op != self.operator:
            warnings.warn(
                f"Deprecated since 19.0, the domain condition {(self.field_expr, self.operator, self.value)!r} should have a lower-case operator",
                DeprecationWarning,
                stacklevel=2,
            )
            return DomainCondition(self.field_expr, op, self.value).checked()
        if op not in CONDITION_OPERATORS:
            self._raise("Invalid operator")
        if op in SUBDOMAIN_OPERATORS and isinstance(self.value, (list, tuple)):
            _check_subdomain_nesting(self.value, MAX_DOMAIN_NESTING)
        value = self.value
        if value is None:
            value = False
        elif isinstance(value, NewId):
            _logger.warning(
                "Domains don't support NewId, use .ids instead, for %r",
                (self.field_expr, self.operator, self.value),
            )
            op = "not in" if op in NEGATIVE_CONDITION_OPERATORS else "in"
            value = []
        elif is_recordset(value):
            _logger.warning(
                "The domain condition %r should not have a value which is a model",
                (self.field_expr, self.operator, self.value),
            )
            value = value.ids
        elif isinstance(value, (Domain, Query, SQL)) and op not in (
            "any",
            "not any",
            "any!",
            "not any!",
            "in",
            "not in",
        ):
            _logger.warning(
                "The domain condition %r should use the 'any' or 'not any' operator.",
                (self.field_expr, self.operator, self.value),
            )
        if value is not self.value:
            return DomainCondition(self.field_expr, op, value)
        return self

    def __invert__(self) -> Domain:
        if "." not in self.field_expr and (
            neg_op := INVERSE_OPERATOR.get(self.operator)
        ):
            return DomainCondition(self.field_expr, neg_op, self.value)
        return super().__invert__()

    def _negate(self, model: BaseModel) -> Domain:
        if neg_op := INVERSE_INEQUALITY.get(self.operator):
            condition = DomainCondition(self.field_expr, neg_op, self.value)
            if self._field(model).falsy_value is None:
                is_null = DomainCondition(self.field_expr, "in", OrderedSet([False]))
                condition = is_null | condition
            return condition

        return super()._negate(model)

    def __iter__(self) -> typing.Iterator[tuple[str, str, object]]:
        field_expr, op, value = self.field_expr, self.operator, self.value
        if isinstance(value, (*COLLECTION_TYPES, Domain)):
            value = list(value)
        yield (field_expr, op, value)

    def __eq__(self, other: object) -> bool:
        return self is other or (
            isinstance(other, DomainCondition)
            and self.field_expr == other.field_expr
            and self.operator == other.operator
            and self.value.__class__ is other.value.__class__
            and _comparand_eq(self.value, other.value)
        )

    def __hash__(self) -> int:
        try:
            return self._hash
        except AttributeError:
            pass
        value = self.value
        try:
            if isinstance(value, (set, frozenset, OrderedSet)):
                h = hash((self.field_expr, self.operator, frozenset(value)))
            elif isinstance(value, list):
                h = hash((self.field_expr, self.operator, tuple(value)))
            else:
                h = hash((self.field_expr, self.operator, value))
        except TypeError:
            h = hash((self.field_expr, self.operator))
        object.__setattr__(self, "_hash", h)
        return h

    def iter_conditions(self) -> typing.Iterator[DomainCondition]:
        yield self

    def map_conditions(self, function: Callable[[DomainCondition], Domain]) -> Domain:
        result = function(self)
        assert isinstance(result, Domain), "result of map_conditions is not a Domain"
        return result

    def _raise(self, message: str, *args, error=ValueError) -> typing.NoReturn:
        message += " in condition (%r, %r, %r)"
        raise error(message % (*args, self.field_expr, self.operator, self.value))

    def _field(self, model: BaseModel) -> Field:
        field = self._field_instance
        if field is None or field.model_name != model._name:
            field, _ = self.__get_field(model)
        return field

    def __get_field(self, model: BaseModel) -> tuple[Field, str]:
        field_name, property_name = parse_field_expr(self.field_expr)
        try:
            field = model._fields[field_name]
        except KeyError:
            self._raise("Invalid field %s.%s", model._name, field_name)
        object.__setattr__(self, "_field_instance", field)
        return field, property_name or ""

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        opt_level = self._opt_level
        if level <= opt_level:
            return self
        if level > opt_level.next_level:
            raise RuntimeError(f"Trying to skip optimization level after {opt_level}")

        if level == OptimizationLevel.BASIC:
            field, property_name = self.__get_field(model)
            if property_name and field.relational:
                sub_domain = DomainCondition(property_name, self.operator, self.value)
                return DomainCondition(field.name, "any", sub_domain)
        else:
            field = self._field(model)

        if level == OptimizationLevel.FULL:
            if field.inherited:
                assert field.related
                parent_fname = field.related.split(".")[0]
                parent_domain = DomainCondition(
                    self.field_expr, self.operator, self.value
                )
                return DomainCondition(parent_fname, "any", parent_domain)

            if field.search and field.name == self.field_expr:
                model._check_field_access(field, "read")
                if field.type == "boolean":
                    for opt in _OPTIMIZATIONS_FOR[level].get("boolean", ()):
                        collapsed = opt(self, model)
                        if isinstance(collapsed, DomainBool):
                            return collapsed
                domain = self._optimize_field_search_method(model)
                if domain != self:
                    domain = domain.optimize(model)
                    if domain != self:
                        return domain

        optimizations = _OPTIMIZATIONS_FOR[level]
        for opt in optimizations.get(self.operator, ()):
            domain = opt(self, model)
            if domain != self:
                return domain
        for opt in optimizations.get(field.type, ()):
            domain = opt(self, model)
            if domain != self:
                return domain

        if (
            self.operator not in STANDARD_CONDITION_OPERATORS
            and level == OptimizationLevel.FULL
        ):
            self._raise("Not standard operator left")

        return self

    def _optimize_field_search_method(self, model: BaseModel) -> Domain:
        field = self._field(model)
        op, value = self.operator, self.value
        original_exception = None
        try:
            computed_domain = field.determine_domain(model, op, value)
        except (NotImplementedError, UserError) as e:
            computed_domain = NotImplemented
            original_exception = e
        else:
            if computed_domain is not NotImplemented:
                return Domain(computed_domain, internal=True)
        if original_exception is None and (inversed_op := INVERSE_OPERATOR.get(op)):
            computed_domain = field.determine_domain(model, inversed_op, value)
            if computed_domain is not NotImplemented:
                return ~Domain(computed_domain, internal=True)
        try:
            if op in ("any!", "not any!"):
                computed_domain = DomainCondition(
                    self.field_expr, op.rstrip("!"), value
                )
                computed_domain = computed_domain._optimize_field_search_method(
                    model.sudo()
                )
                _logger.warning("Field %s should implement any! operator", field)
                return computed_domain
        except (NotImplementedError, UserError) as e:
            if original_exception is None:
                original_exception = e
        try:
            if op == "in":
                return Domain.OR(
                    Domain(field.determine_domain(model, "=", v), internal=True)
                    for v in value
                )
            elif op == "not in":
                return Domain.AND(
                    Domain(field.determine_domain(model, "!=", v), internal=True)
                    for v in value
                )
        except (NotImplementedError, UserError) as e:
            if original_exception is None:
                original_exception = e
        if original_exception:
            raise original_exception
        raise UserError(
            model.env._(
                "Unsupported operator on %(field_label)s %(model_label)s in %(domain)s",
                domain=repr(self),
                field_label=self._field(model).get_description(model.env, ["string"])[
                    "string"
                ],
                model_label=f"{model.env['ir.model']._get(model._name).name!r} ({model._name})",
            )
        )

    def _is_search_defined(self, records: BaseModel) -> bool:
        field = self._field(records)
        return bool((field.search and field.name == self.field_expr) or field.inherited)

    def _search_defined_predicate(
        self, records: BaseModel
    ) -> Callable[[BaseModel], bool]:
        real_ids = [id_ for id_ in records._ids if id_]
        matched: set = set()
        if real_ids:
            query = records.with_context(active_test=False)._search(
                DomainCondition("id", "in", OrderedSet(real_ids)) & self
            )
            matched = set(query.get_result_ids())

        if all(records._ids):
            return lambda rec: rec._ids[0] in matched

        in_memory = self._value_predicate(records)
        return lambda rec: rec._ids[0] in matched if rec._ids[0] else in_memory(rec)

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        if not records:
            return lambda _: False

        if self._opt_level < OptimizationLevel.DYNAMIC_VALUES:
            with _recursion_error_as_value_error():
                domain = self._optimize(records, OptimizationLevel.DYNAMIC_VALUES)
            return domain._as_predicate(records)

        op = self.operator
        if op in ("child_of", "parent_of"):
            with _recursion_error_as_value_error():
                domain = self._optimize(records, OptimizationLevel.FULL)
            return domain._as_predicate(records)

        if self._is_search_defined(records):
            return self._search_defined_predicate(records)

        return self._value_predicate(records)

    def _value_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        op = self.operator
        if not all(records._ids):
            fallback = getattr(self, "_predicate_fallback", None)
            if fallback is not None:
                return fallback._as_predicate(records)

        if op not in STANDARD_CONDITION_OPERATORS:
            raise RuntimeError(f"Expecting a sub-set of operators, got {op!r}")
        field_expr, value = self.field_expr, self.value
        positive_operator = NEGATIVE_CONDITION_OPERATORS.get(op, op)

        if isinstance(value, SQL):
            if positive_operator == op:
                condition = self
                op = "any!"
            else:
                condition = ~self
                op = "not any!"
            positive_operator = "any!"
            field_expr = "id"
            value = records.with_context(active_test=False)._search(
                DomainCondition("id", "in", OrderedSet(records.ids)) & condition
            )
            assert isinstance(value, Query)

        if isinstance(value, Query):
            if positive_operator not in ("in", "any", "any!"):
                self._raise(
                    "Cannot filter using Query without the 'any' or 'in' operator"
                )
            if positive_operator != "in":
                op = "in" if positive_operator == op else "not in"
                positive_operator = "in"
            value = set(value.get_result_ids())
            return DomainCondition(field_expr, op, value)._as_predicate(records)

        field = self._field(records)
        if field_expr == "display_name":
            field_expr = "display_name.no_error"
        elif field_expr == "id":
            field_expr = "id.origin"

        func = field.filter_function(records, field_expr, positive_operator, value)
        return func if positive_operator == op else lambda rec: not func(rec)

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        field_expr, op, value = self.field_expr, self.operator, self.value
        if op not in STANDARD_CONDITION_OPERATORS:
            raise RuntimeError(
                f"Invalid operator {op!r} for SQL in domain term {(field_expr, op, value)!r}"
            )
        if self._opt_level < OptimizationLevel.FULL:
            raise RuntimeError(
                f"Must fully optimize before generating the query {(field_expr, op, value)}"
            )
        if self._opt_model_name not in (None, model._name):
            raise RuntimeError(
                f"Domain optimized for {self._opt_model_name!r} cannot generate "
                f"SQL for {model._name!r} in term {(field_expr, op, value)}"
            )

        field = self._field(model)
        model._check_field_access(field, "read")
        return field.condition_to_sql(field_expr, op, value, model, alias, query)


ANY_TYPES = (Domain, Query, SQL)

#: The five underscore names this module used to list here --
#: ``_FALSE_DOMAIN``, ``_MERGE_OPTIMIZATIONS``, ``_OPTIMIZATIONS_FOR``,
#: ``_TRUE_DOMAIN`` and ``_optimize_nary_sort_key`` -- are gone from it.
#: ``optimizations.py`` imports each by name from ``.ast``, which needs no
#: ``__all__`` entry; listing them said "public" where the underscore says
#: "private", about the module's most sharply internal objects (the optimizer
#: registries).
__all__ = [
    "ANY_TYPES",
    "MAX_OPTIMIZE_ITERATIONS",
    "Domain",
    "DomainAnd",
    "DomainBool",
    "DomainCondition",
    "DomainCustom",
    "DomainNary",
    "DomainNot",
    "DomainOr",
    "OptimizationLevel",
]
