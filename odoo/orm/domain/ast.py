"""Domain AST classes.

The ``Domain`` hierarchy: ``Domain`` (base + factory), ``DomainBool``
(TRUE/FALSE), ``DomainNot`` (negation), ``DomainNary`` / ``DomainAnd`` /
``DomainOr``, ``DomainCustom`` (custom SQL), ``DomainCondition`` (a
``(field, operator, value)`` leaf). Also defines ``OptimizationLevel`` and the
optimization registries populated by ``optimizations.py``.
"""

import collections
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
    """Indicator whether the domain was optimized."""

    NONE = 0
    BASIC = enum.auto()
    DYNAMIC_VALUES = enum.auto()
    FULL = enum.auto()

    @functools.cached_property
    def next_level(self) -> OptimizationLevel:
        """Return the next optimization level."""
        # raise (not assert): a clearer message than the ValueError that
        # ``OptimizationLevel(int(FULL)+1)`` would raise under python -O.
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


def _iter_subdomains(node: Domain) -> typing.Iterator[Domain]:
    """Yield the direct operator-child domains of *node* (none for leaves).

    Only the n-ary/not structure; ``any``/``not any`` sub-domains are validated
    on their own :meth:`Domain.__new__` parse, so not re-walked here.
    """
    if isinstance(node, DomainNary):  # DomainAnd / DomainOr
        yield from node.children
    elif isinstance(node, DomainNot):
        yield node.child


def _check_domain_nesting(domain: Domain, max_depth: int) -> None:
    """Raise ``ValueError`` if *domain* nests deeper than *max_depth*.

    Explicit-stack DFS with early exit (never recurses itself), turning a
    deep-domain ``RecursionError`` into a catchable validation error.
    """
    stack: list[tuple[Domain, int]] = [(domain, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            raise ValueError(
                f"Domain nesting too deep (>{max_depth} levels); refusing to "
                f"build it to avoid a RecursionError during evaluation"
            )
        for child in _iter_subdomains(node):
            stack.append((child, depth + 1))


# Types for optimization functions
ANY_TYPES = (typing.ForwardRef("Domain"), Query, SQL)

if typing.TYPE_CHECKING:
    ConditionOptimization = Callable[["DomainCondition", "BaseModel"], "Domain"]
    MergeOptimization = Callable[
        [type["DomainNary"], list["Domain"], "BaseModel"], list["Domain"]
    ]

# Optimization registries - populated by optimization functions in optimizations.py
_OPTIMIZATIONS_FOR: dict[OptimizationLevel, dict[str, list]] = {
    level: collections.defaultdict(list)
    for level in OptimizationLevel
    if level != OptimizationLevel.NONE
}
_MERGE_OPTIMIZATIONS: list = []


def _optimize_nary_sort_key(domain: Domain) -> tuple[str, str, str]:
    """Sort key grouping nary children by (field, operator type, operator).

    Equivalent conditions sort together, yielding canonical domains and SQL
    ordered by field name (better DB caching).

    Load-bearing invariant: nary merge passes (``_MERGE_OPTIMIZATIONS``) only
    combine *adjacent* conditions, so this key MUST place every co-mergeable
    pair next to each other regardless of input order. Optimization confluence
    depends on it; locked in by ``tests/models/test_domain_confluence.py``.
    """
    if isinstance(domain, DomainCondition):
        # group the same field and same operator together
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
        return domain.field_expr, order, op
    elif hasattr(domain, "OPERATOR") and isinstance(domain.OPERATOR, str):
        # in python; '~' > any letter
        return "~", "", domain.OPERATOR
    else:
        return "~", "~", domain.__class__.__name__


# Domain definition and manipulation


class Domain:
    """Representation of a domain as an AST."""

    # Abstract base, but not marked ABC: __new__ is overridden so Domain doubles
    # as a factory for the concrete subtypes while keeping `isinstance` working.
    __slots__ = ("_opt_level",)
    _opt_level: OptimizationLevel

    def __new__(cls, *args: object, internal: bool = False) -> Domain:
        """Build a domain AST.

        A single argument is a ``Domain``, a list representation, or a bool.
        Three arguments form one condition: field (str), operator (str), value::

            Domain([("a", "=", 5), ("b", "=", 8)])
            Domain("a", "=", 5) & Domain("b", "=", 8)

        The ``'any!'`` / ``'not any!'`` operators are allowed in conditions
        (``Domain('a', 'any!', dom)``) but not in domain lists unless
        ``internal=True``.
        """
        if len(args) > 1:
            if isinstance(args[0], str):
                return DomainCondition(*args).checked()
            # special cases like True/False constants
            if args == TRUE_LEAF:
                return _TRUE_DOMAIN
            if args == FALSE_LEAF:
                return _FALSE_DOMAIN
            raise TypeError(f"Domain() invalid arguments: {args!r}")

        arg = args[0]
        if isinstance(arg, Domain):
            return arg
        # Accept both ``[]`` and ``()`` as TRUE (``Domain(())`` must not fall
        # through to the malformed-domain path).
        if arg is True or arg in ([], ()):
            return _TRUE_DOMAIN
        if arg is False:
            return _FALSE_DOMAIN
        if arg is NotImplemented:
            raise NotImplementedError

        # parse as a list, inside __new__ to avoid implicit __init__ calls
        if not isinstance(arg, (list, tuple)):
            raise TypeError(f"Domain() invalid argument type for domain: {arg!r}")
        # Fast path for the common single-condition domain, skipping the stack.
        if len(arg) == 1:
            item = arg[0]
            if isinstance(item, (tuple, list)) and len(item) == 3:
                if internal:
                    # parse subdomain values for any/any!/not any/not any!
                    if item[1] in SUBDOMAIN_OPERATORS and isinstance(
                        item[2], (list, tuple)
                    ):
                        item = (
                            item[0],
                            item[1],
                            Domain(item[2], internal=True),
                        )
                elif item[1] in INTERNAL_CONDITION_OPERATORS:
                    raise ValueError(f"Domain() invalid item in domain: {item!r}")
                return Domain(*item)
            if isinstance(item, Domain):
                return item
        stack: list[Domain] = []
        try:
            for item in reversed(arg):
                if isinstance(item, (tuple, list)) and len(item) == 3:
                    if internal:
                        if item[1] in SUBDOMAIN_OPERATORS and isinstance(
                            item[2], (list, tuple)
                        ):
                            item = (
                                item[0],
                                item[1],
                                Domain(item[2], internal=True),
                            )
                    elif item[1] in INTERNAL_CONDITION_OPERATORS:
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
        # Reject pathologically deep ASTs before any recursive traversal can
        # hit a RecursionError (applies to internal sub-domain parses too).
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
        """Create a custom domain.

        :param to_sql: callable(model, alias, query) that returns the SQL
        :param predicate: callable(record) that checks whether a record is kept
                          when filtering
        """
        return DomainCustom(to_sql, predicate)

    @staticmethod
    def AND(items: Iterable[object]) -> Domain:
        """Build the conjuction of domains: (item1 AND item2 AND ...)"""
        return DomainAnd.apply(Domain(item) for item in items)

    @staticmethod
    def OR(items: Iterable[object]) -> Domain:
        """Build the disjuction of domains: (item1 OR item2 OR ...)"""
        return DomainOr.apply(Domain(item) for item in items)

    def __setattr__(self, name: str, value: object) -> None:
        msg = "Domain objects are immutable"
        raise TypeError(msg)

    def __delattr__(self, name: str) -> None:
        msg = "Domain objects are immutable"
        raise TypeError(msg)

    def __and__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, Domain):
            # absorbing element / identity shortcut
            if isinstance(other, DomainBool):
                return self if other.value else other
            return DomainAnd.apply([self, other])
        return NotImplemented

    def __or__(self, other: object) -> Domain | type[NotImplemented]:
        if isinstance(other, Domain):
            # absorbing element / identity shortcut
            if isinstance(other, DomainBool):
                return other if other.value else self
            return DomainOr.apply([self, other])
        return NotImplemented

    def __invert__(self) -> Domain:
        return DomainNot(self)

    def _negate(self, model: BaseModel) -> Domain:
        """Apply (propagate) negation onto this domain."""
        return ~self

    def __add__(self, other: object) -> Domain | list[object]:
        """Deprecated list concatenation; use ``&`` (AND) or ``|`` (OR).

        Domain + Domain is ``&``; Domain + list concatenates as raw (possibly
        unnormalized) lists. Kept for backward compatibility.
        """
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
        """Deprecated ``list + Domain``; returns a (possibly unnormalized) list."""
        warnings.warn(
            "list + Domain is deprecated, convert the list to a Domain first",
            DeprecationWarning,
            stacklevel=2,
        )
        return other + list(self)

    def __bool__(self) -> bool:
        """Whether the domain is not TRUE (so the TRUE domain is falsy).

        Deprecated; prefer ``is_true()`` / ``is_false()``. The deprecation
        warning is deferred until core callers stop using ``if domain:``.
        """
        return not self.is_true()

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError

    def __iter__(self) -> typing.Iterator[object]:
        """Yield the polish-notation domain list (backward compatibility)."""
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
        """Yield the simple conditions of the domain."""
        yield from ()

    def map_conditions(self, function: Callable[[DomainCondition], Domain]) -> Domain:
        """Map *function* over each condition and return the combined result."""
        return self

    def validate(self, model: BaseModel) -> None:
        """Validate the domain, raising on error."""
        # full optimization walks every field, validating along the way
        self._optimize(model, OptimizationLevel.FULL)

    def _as_predicate(self, records: M) -> Callable[[M], bool]:
        """Return a predicate testing whether a single record satisfies self.

        Used to implement ``Model.filtered_domain``.
        """
        raise NotImplementedError

    def optimize(self, model: BaseModel) -> Domain:
        """Rewrite the domain into a canonical, logically equivalent form.

        Basic level only: transaction-independent, depending solely on the
        model's field definitions (no model-specific overrides), so the result
        is reusable across transactions and suitable for the client side.
        """
        return self._optimize(model, OptimizationLevel.BASIC)

    def optimize_full(self, model: BaseModel) -> Domain:
        """Rewrite the domain applying basic and advanced optimizations.

        Advanced optimizations may use model-specific overrides (field search
        methods) and resolve inherited/non-stored fields, so equivalence holds
        only at this point in the transaction.
        """
        return self._optimize(model, OptimizationLevel.FULL)

    @typing.final
    def _optimize(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Optimize to a fixed point, advancing one level at a time up to *level*.

        Termination (``MAX_OPTIMIZE_ITERATIONS`` is only a backstop):
        ``_opt_level`` advances monotonically and within each level the
        registered passes are confluent and non-size-increasing (see
        ``_optimize_nary_sort_key``). The ``==`` below (not ``is``) is required:
        a no-merge ``_optimize_step`` may still return a new, value-equal node
        with sorted children; ``is`` would never advance the level and spin to
        the backstop. Each ``__eq__`` short-circuits on identity, so the common
        no-op case stays O(1).
        """
        domain, previous, count = self, None, 0
        while domain._opt_level < level:
            if (count := count + 1) > MAX_OPTIMIZE_ITERATIONS:
                msg = "Domain.optimize: too many loops"
                raise RecursionError(msg)
            next_level = domain._opt_level.next_level
            previous, domain = domain, domain._optimize_step(model, next_level)
            # bump the level when stable (DomainBool etc. start already at FULL)
            if domain == previous and domain._opt_level < next_level:
                object.__setattr__(domain, "_opt_level", next_level)
        return domain

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Run one level of optimizations (overridden per subclass)."""
        return self

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        """Build the SQL to inject into the query; optimize the domain first."""
        raise NotImplementedError


class DomainBool(Domain):
    """Constant domain: True/False

    It is NOT considered as a condition and these constants are removed
    from nary domains.
    """

    __slots__ = ("value",)
    value: bool

    # Pre-built SQL constants — avoids SQL() allocation on every _to_sql call
    _SQL_TRUE = SQL("TRUE")
    _SQL_FALSE = SQL("FALSE")

    def __new__(cls, value: bool):
        self = object.__new__(cls)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "_opt_level", OptimizationLevel.FULL)
        return self

    def __eq__(self, other: object) -> bool:
        return self is other  # because this class has two instances only

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


# singletons, available through Domain.TRUE and Domain.FALSE
_TRUE_DOMAIN = DomainBool(True)
_FALSE_DOMAIN = DomainBool(False)


class DomainNot(Domain):
    """Negation domain, contains a single child"""

    OPERATOR = "!"

    __slots__ = ("child",)
    child: Domain

    def __new__(cls, child: Domain):
        """Create a domain which is the inverse of the child."""
        self = object.__new__(cls)
        object.__setattr__(self, "child", child)
        object.__setattr__(self, "_opt_level", OptimizationLevel.NONE)
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
    """Domain for a nary operator: AND or OR with multiple children"""

    OPERATOR: str
    OPERATOR_SQL: SQL = SQL(" ??? ")
    ZERO: DomainBool = _FALSE_DOMAIN  # default for lint checks

    __slots__ = ("children",)
    children: tuple[Domain, ...]

    def __new__(cls, children: tuple[Domain, ...]):
        """Create the n-ary domain with at least 2 conditions."""
        # raise (not assert): under python -O a < 2-child nary is a malformed
        # AST that would otherwise crash later in obscure traversal code.
        if len(children) < 2:
            raise ValueError(
                f"DomainNary requires at least 2 children, got {len(children)}"
            )
        self = object.__new__(cls)
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "_opt_level", OptimizationLevel.NONE)
        return self

    @classmethod
    def apply(cls, items: Iterable[Domain]) -> Domain:
        """Return the result of combining AND/OR to a collection of domains."""
        children = cls._flatten(items)
        if len(children) == 1:
            return children[0]
        return cls(tuple(children))

    @classmethod
    def _flatten(cls, children: Iterable[Domain]) -> list[Domain]:
        """Flatten children for this class's boolean op (AND/OR).

        Boolean subdomains are simplified and same-class subdomains are inlined.
        The returned list is never empty.
        """
        result: list[Domain] = []
        for child in children:
            if isinstance(child, DomainBool):
                if child != cls.ZERO:
                    return [child]
            elif isinstance(child, cls):
                result.extend(child.children)  # same class, flatten
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
        """Return the inverted nary type, AND/OR"""
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
        size = len(children)
        if size > 1:
            # sort to group children by field and operator
            children.sort(key=_optimize_nary_sort_key)
            cls = type(self)
            for merge in _MERGE_OPTIMIZATIONS:
                children = merge(cls, children, model)
                if len(children) < size:
                    break
            else:
                # no merge: reuse self if children are identical. The length
                # check guarantees strict=True (and guards future refactors).
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
    """Domain: AND with multiple children"""

    __slots__ = ()
    OPERATOR = "&"
    OPERATOR_SQL = SQL(" AND ")
    ZERO = _TRUE_DOMAIN

    @classproperty
    def INVERSE(self) -> type[DomainNary]:
        return DomainOr

    def __and__(self, other: object) -> Domain | type[NotImplemented]:
        # append children directly when both sides are AND
        if isinstance(other, DomainAnd):
            return DomainAnd(self.children + other.children)
        return super().__and__(other)

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        predicates = tuple(child._as_predicate(records) for child in self.children)

        def and_predicate(record: BaseModel) -> bool:
            return all(pred(record) for pred in predicates)

        return and_predicate


class DomainOr(DomainNary):
    """Domain: OR with multiple children"""

    __slots__ = ()
    OPERATOR = "|"
    OPERATOR_SQL = SQL(" OR ")
    ZERO = _FALSE_DOMAIN

    @classproperty
    def INVERSE(self) -> type[DomainNary]:
        return DomainAnd

    def __or__(self, other: object) -> Domain | type[NotImplemented]:
        # append children directly when both sides are OR
        if isinstance(other, DomainOr):
            return DomainOr(self.children + other.children)
        return super().__or__(other)

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        predicates = tuple(child._as_predicate(records) for child in self.children)

        def or_predicate(record: BaseModel) -> bool:
            return any(pred(record) for pred in predicates)

        return or_predicate


class DomainCustom(Domain):
    """Domain condition that generates directly SQL and possibly a ``filtered`` predicate."""

    __slots__ = ("_filtered", "_sql")

    _filtered: Callable[[BaseModel], bool] | None
    _sql: Callable[[BaseModel, str, Query], SQL]

    def __new__(
        cls,
        sql: Callable[[BaseModel, str, Query], SQL],
        filtered: Callable[[BaseModel], bool] | None = None,
    ):
        """Create a custom domain.

        :param sql: ``callable(model, alias, query)`` implementing ``_to_sql``.
        :param filtered: ``callable(record)`` deciding whether a record is kept
            for ``Model.filtered``.
        """
        self = object.__new__(cls)
        object.__setattr__(self, "_sql", sql)
        object.__setattr__(self, "_filtered", filtered)
        object.__setattr__(self, "_opt_level", OptimizationLevel.FULL)
        return self

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        if self._filtered is not None:
            return self._filtered
        # by default, run the SQL query
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
        yield from ()
        raise NotImplementedError

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        return self._sql(model, alias, query)


class DomainCondition(Domain):
    """Domain condition on field: (field, operator, value)

    A field (or expression) is compared to a value. The list of supported
    operators are described in CONDITION_OPERATORS.
    """

    __slots__ = ("_field_instance", "field_expr", "operator", "value")
    _field_instance: Field | None  # mutable cached property
    field_expr: str
    operator: str
    value: typing.Any

    def __new__(cls, field_expr: str, operator: str, value: object) -> DomainCondition:
        """Build a simple condition (field name/path, operator, value)."""
        self = object.__new__(cls)
        object.__setattr__(self, "field_expr", field_expr)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "_field_instance", None)
        object.__setattr__(self, "_opt_level", OptimizationLevel.NONE)
        return self

    def checked(self) -> DomainCondition:
        """Validate `self` and return it if correct, otherwise raise an exception."""
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
        # Normalize common value mistakes here to avoid recreating the domain:
        # NewId is not a value, records become their ids, and Query/Domain
        # values need a relational operator.
        from ..models import BaseModel

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
        elif isinstance(value, BaseModel):
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
            # accept SQL object in the right part for simple operators
            # use case: compare 2 fields
            _logger.warning(
                "The domain condition %r should use the 'any' or 'not any' operator.",
                (self.field_expr, self.operator, self.value),
            )
        if value is not self.value:
            return DomainCondition(self.field_expr, op, value)
        return self

    def __invert__(self) -> Domain:
        # only simple fields, not expressions; inequalities go through _negate()
        if "." not in self.field_expr and (
            neg_op := INVERSE_OPERATOR.get(self.operator)
        ):
            return DomainCondition(self.field_expr, neg_op, self.value)
        return super().__invert__()

    def _negate(self, model: BaseModel) -> Domain:
        # operator inversion is handled by construction, except for inequalities
        # which need the field's type
        if neg_op := INVERSE_INEQUALITY.get(self.operator):
            # inverse, and OR in "field is null" when the field has no falsy
            # value (a falsy value is handled correctly by SQL generation)
            condition = DomainCondition(self.field_expr, neg_op, self.value)
            if self._field(model).falsy_value is None:
                is_null = DomainCondition(self.field_expr, "in", OrderedSet([False]))
                condition = is_null | condition
            return condition

        return super()._negate(model)

    def __iter__(self) -> typing.Iterator[tuple[str, str, object]]:
        field_expr, op, value = self.field_expr, self.operator, self.value
        # normalize domain/set values to a list
        if isinstance(value, (*COLLECTION_TYPES, Domain)):
            value = list(value)
        yield (field_expr, op, value)

    def __eq__(self, other: object) -> bool:
        return self is other or (
            isinstance(other, DomainCondition)
            and self.field_expr == other.field_expr
            and self.operator == other.operator
            # stricter than ==: reject `OrderedSet([x]) == {x}` so optimizations
            # always converge on OrderedSet values
            and self.value.__class__ is other.value.__class__
            and self.value == other.value
        )

    def __hash__(self) -> int:
        return hash(self.field_expr) ^ hash(self.operator) ^ hash(self.value)

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
        """Return the cached Field for the expression."""
        field = self._field_instance  # type: ignore[arg-type]
        if field is None or field.model_name != model._name:
            field, _ = self.__get_field(model)
        return field

    def __get_field(self, model: BaseModel) -> tuple[Field, str]:
        """Resolve the field (raising if invalid) and cache it."""
        field_name, property_name = parse_field_expr(self.field_expr)
        try:
            field = model._fields[field_name]
        except KeyError:
            self._raise("Invalid field %s.%s", model._name, field_name)
        # cache on the instance, bypassing immutability
        object.__setattr__(self, "_field_instance", field)
        return field, property_name or ""

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Optimization step.

        Validate the field, decompose paths into ``any`` sub-domains, run the
        field's search method for non-stored fields, then dispatch the
        registered optimizations for the operator and field type.
        """
        # raise (not assert): under python -O, skipping a level would silently
        # yield an under-optimized domain.
        if level is not self._opt_level.next_level:
            raise RuntimeError(
                f"Trying to skip optimization level after {self._opt_level}"
            )

        if level == OptimizationLevel.BASIC:
            # decompose a path into an 'any' sub-domain
            field, property_name = self.__get_field(model)
            if property_name and field.relational:
                sub_domain = DomainCondition(property_name, self.operator, self.value)
                return DomainCondition(field.name, "any", sub_domain)
        else:
            field = self._field(model)

        if level == OptimizationLevel.FULL:
            # resolve inherited fields. inherits implies delegate=True and
            # bypass_search_access=True, so the 'any' below adds no permissions.
            if field.inherited:
                assert field.related
                parent_fname = field.related.split(".")[0]
                parent_domain = DomainCondition(
                    self.field_expr, self.operator, self.value
                )
                return DomainCondition(parent_fname, "any", parent_domain)

            if field.search and field.name == self.field_expr:
                domain = self._optimize_field_search_method(model)
                # only basic optimization, to make value types comparable
                # without recursing endlessly
                domain = domain.optimize(model)
                if domain != self:
                    return domain

        # dispatch optimizations for the operator, then the field type
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
        # retry with the positive operator
        if original_exception is None and (inversed_op := INVERSE_OPERATOR.get(op)):
            computed_domain = field.determine_domain(model, inversed_op, value)
            if computed_domain is not NotImplemented:
                return ~Domain(computed_domain, internal=True)
        # any!/not any! fallback: not strictly equivalent, the search runs sudo
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
        # fall back to fields implementing only '=' / '!='
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

    def _as_predicate(self, records: BaseModel) -> Callable[[BaseModel], bool]:
        if not records:
            return lambda _: False

        if self._opt_level < OptimizationLevel.DYNAMIC_VALUES:
            return self._optimize(
                records, OptimizationLevel.DYNAMIC_VALUES
            )._as_predicate(records)

        op = self.operator
        if op in ("child_of", "parent_of"):
            # hierarchy operators need full optimization (parent_path expansion)
            # before becoming a predicate; rare here, so the SQL round-trip is
            # not worth specializing in memory
            return self._optimize(records, OptimizationLevel.FULL)._as_predicate(
                records
            )

        # raise (not assert): hold the contract under python -O
        if op not in STANDARD_CONDITION_OPERATORS:
            raise RuntimeError(
                f"Expecting a sub-set of operators, got {op!r}"
            )
        field_expr, value = self.field_expr, self.value
        positive_operator = NEGATIVE_CONDITION_OPERATORS.get(op, op)

        if isinstance(value, SQL):
            # turn the SQL value into a Query via a sub-search
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
            # rebuild the condition as an 'in' against the resolved ids
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
            # when searching by name, ignore AccessError
            field_expr = "display_name.no_error"
        elif field_expr == "id":
            # for new records, compare to their origin
            field_expr = "id.origin"

        func = field.filter_function(records, field_expr, positive_operator, value)
        return func if positive_operator == op else lambda rec: not func(rec)

    def _to_sql(self, model: BaseModel, alias: str, query: Query) -> SQL:
        field_expr, op, value = self.field_expr, self.operator, self.value
        # raise (not assert): under python -O an unoptimized or non-standard
        # condition would otherwise produce malformed/wrong SQL silently
        if op not in STANDARD_CONDITION_OPERATORS:
            raise RuntimeError(
                f"Invalid operator {op!r} for SQL in domain term {(field_expr, op, value)!r}"
            )
        if self._opt_level < OptimizationLevel.FULL:
            raise RuntimeError(
                f"Must fully optimize before generating the query {(field_expr, op, value)}"
            )

        field = self._field(model)
        model._check_field_access(field, "read")
        return field.condition_to_sql(field_expr, op, value, model, alias, query)


# Update ANY_TYPES now that Domain is defined
ANY_TYPES = (Domain, Query, SQL)

__all__ = [
    "ANY_TYPES",
    "MAX_OPTIMIZE_ITERATIONS",
    "_FALSE_DOMAIN",
    "_MERGE_OPTIMIZATIONS",
    "_OPTIMIZATIONS_FOR",
    # Singletons
    "_TRUE_DOMAIN",
    # Domain classes
    "Domain",
    "DomainAnd",
    "DomainBool",
    "DomainCondition",
    "DomainCustom",
    "DomainNary",
    "DomainNot",
    "DomainOr",
    # Optimization infrastructure
    "OptimizationLevel",
    "_optimize_nary_sort_key",
]
