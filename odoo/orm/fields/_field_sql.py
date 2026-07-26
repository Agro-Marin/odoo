"""SQL and domain-condition generation for a field.

Extracted from the Field god-class; mixed into Field (base.py).
"""

import operator as pyoperator
import re
import typing
import warnings
from collections.abc import (
    Callable,
)
from collections.abc import Set as AbstractSet

from odoo.tools import (
    SQL,
    Query,
)

from ..domain import Domain
from ..primitives import COLLECTION_TYPES, SQL_OPERATORS
from ._field_stubs import _FieldStubs

if typing.TYPE_CHECKING:
    from .._typing import BaseModel, ModelLike

    M = typing.TypeVar("M", bound=BaseModel)


PYTHON_INEQUALITY_OPERATOR: dict[str, Callable[[object, object], bool]] = {
    "<": pyoperator.lt,
    ">": pyoperator.gt,
    "<=": pyoperator.le,
    ">=": pyoperator.ge,
}

IN_TO_ANY_THRESHOLD = 100


class _FieldSqlMixin(_FieldStubs):
    """SQL and domain-condition generation for a field."""

    def to_sql(self, model: ModelLike, alias: str) -> SQL:
        """Return an :class:`SQL` object that represents the value of the given
        field from the given table alias.

        The query object is necessary for fields that need to add tables to the query.
        """
        if not self.store or not self.column_type:
            raise ValueError(f"Cannot convert {self} to SQL because it is not stored")
        sql_field = SQL.identifier(alias, self.name, to_flush=self)
        if self.company_dependent:
            fallback = self.get_company_dependent_fallback(model)
            fallback = self.convert_to_column(
                self.convert_to_write(fallback, model), model
            )
            sql_field = SQL(
                "COALESCE(%(column)s->%(company_id)s,to_jsonb(%(fallback)s::%(column_type)s))",
                column=sql_field,
                company_id=str(model.env.company.id),
                fallback=fallback,
                column_type=SQL(self._column_type[1]),
            )
            if self.type in ("boolean", "integer", "float", "monetary"):
                return SQL("(%s)::%s", sql_field, SQL(self._column_type[1]))
            return SQL("(%s->>0)::%s", sql_field, SQL(self._column_type[1]))

        return sql_field

    def property_to_sql(
        self,
        field_sql: SQL,
        property_name: str,
        model: ModelLike,
        alias: str,
        query: Query,
    ) -> SQL:
        """Return an :class:`SQL` object that represents the value of the given
        expression from the given table alias.

        The query object is necessary for fields that need to add tables to the query.
        """
        raise ValueError(f"Invalid field property {property_name!r} on {self}")

    def _comparand_to_column(self, value: typing.Any, model: BaseModel) -> typing.Any:
        """Return the SQL parameter comparing *value* against this field's column.

        Distinct from :meth:`convert_to_column`, which converts a value for
        **storage**.  Storage conversion is allowed to be lossy -- ``Integer``
        truncates (``int(2.5) == 2``), ``Float(digits=...)`` rounds
        (``float_round(0.01000004, 6) == 0.01``) -- because the column cannot
        hold more than that anyway.  A *comparand* is not stored: it only has to
        order and compare correctly against the stored values, so it must be
        converted **exactly**.  Coercing it through storage conversion silently
        moves the comparison boundary and, since the Python evaluator does not
        apply it, makes the two evaluators disagree:

        * ``('sequence', '<', 2.5)`` became ``< 2`` and dropped every record
          with ``sequence == 2`` (in *both* evaluators, which share
          :meth:`_inequality_comparand`);
        * ``('sequence', '=', 2.5)`` matched ``sequence == 2`` under
          ``search()`` and nothing under ``filtered_domain()``;
        * ``('rounding', '=', 0.01000004)`` on a ``Float(digits=(12, 6))``
          matched every ``0.01`` row under ``search()`` and nothing under
          ``filtered_domain()``.

        The default keeps the historical behaviour (storage conversion); the
        numeric field classes override it to stay exact.  PostgreSQL promotes
        both operands to a common numeric type, so an ``int4`` column compares
        exactly against ``2.5`` and a ``numeric`` column against a full-precision
        ``Decimal``.
        """
        return self.convert_to_column(value, model, validate=False)

    def _inequality_comparand(self, value: typing.Any, model: BaseModel) -> typing.Any:
        """Coerce the right-hand side of an ordering comparison (``<``, ``>``,
        ``<=``, ``>=``) to the field's cache format.

        **Single source of truth** for the two evaluators of the same domain:
        :meth:`_condition_to_sql` (SQL) and :meth:`filter_function` (Python).
        They used to coerce independently -- SQL through ``convert_to_cache``,
        Python not at all -- so ``search(domain)`` and
        ``recs.filtered_domain(domain)`` could disagree on identical inputs:

        * ``('int_field', '>', '3')`` (a string comparand, the ordinary shape
          coming from the web client / ``ir.filters``): SQL coerced to ``3`` and
          matched; Python left ``'3'`` and raised ``TypeError: '>' not supported
          between instances of 'int' and 'str'`` while *building* the predicate.
        * ``('html_field', '<', 'note')``: SQL compared against the sanitized
          ``<p>note</p>`` (what is actually stored); Python compared against the
          raw ``'note'``, returning a different set of records.

        Only called when the field has a ``falsy_value`` (Char/Text/Html,
        Integer, Float/Monetary, Boolean) -- the case both call sites already
        special-cased; fields without one map a falsy comparand to SQL NULL in
        ``convert_to_column`` instead.  The trailing ``or falsy_value``
        normalizes a falsy comparand (``False`` / ``None`` / ``''`` / ``0``) to
        the field's own falsy sentinel, so ``NULL`` and the sentinel keep
        comparing alike on both sides.

        Like its SQL counterpart :meth:`_comparand_to_column`, this must be
        **exact**: the numeric field classes override it so that a threshold is
        not truncated/rounded down to what the column happens to be able to
        store (see there).
        """
        return self.convert_to_cache(value, model) or self.falsy_value

    def condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        """Return an :class:`SQL` object that represents the domain condition
        given by the triple ``(field_expr, operator, value)`` with the given
        table alias, and in the context of the given query.

        This method should use the model to resolve the SQL and check access
        of the field.
        """
        sql_expr = self._condition_to_sql(
            field_expr, operator, value, model, alias, query
        )
        if self.company_dependent:
            sql_expr = self._condition_to_sql_company(
                sql_expr, field_expr, operator, value, model, alias, query
            )
        return sql_expr

    def _condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        sql_field = model._field_to_sql(alias, field_expr, query)

        if field_expr == self.name:

            def _value_to_column(v: typing.Any) -> typing.Any:
                return self._comparand_to_column(v, model)

        else:

            def _value_to_column(v: typing.Any) -> typing.Any:
                return v

        if operator in SQL_OPERATORS and isinstance(value, SQL):
            warnings.warn(
                "Since 19.0, use Domain.custom(to_sql=lambda model, alias, query: SQL(...))",
                DeprecationWarning,
                stacklevel=2,
            )
            return SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], value)

        can_be_null = self not in model.env.registry.not_null_fields

        if operator in ("in", "not in"):
            assert isinstance(value, COLLECTION_TYPES), (
                f"condition_to_sql() 'in' operator expects a collection, not a {value!r}"
            )
            # A comparand the column cannot represent equals no stored value, so
            # it is dropped from the set rather than raised on -- the rule
            # ``_optimize_numeric_comparand`` documents for numeric fields and
            # ``Id.filter_function`` already applies on the Python side ("dropped
            # from an equality set ... which is what the SQL side concludes
            # too").  The SQL side did not: it raised, so ``('id', '=', 'abc')``
            # aborted ``search()`` while ``filtered_domain()`` matched nothing.
            # An *ordering* comparison still raises, in both evaluators.
            # ``null_in_condition`` is tracked explicitly: inferring it from a
            # length difference would read a dropped value as a null comparand.
            converted: list[typing.Any] = []
            null_in_condition = False
            for v in value:
                if v is False or v is None:
                    null_in_condition = True
                    continue
                try:
                    converted.append(_value_to_column(v))
                except ValueError, TypeError:
                    continue
            params = tuple(converted)
            if not params and not null_in_condition:
                return SQL("FALSE") if operator == "in" else SQL("TRUE")
            if (null_value := self.falsy_value) is not None:
                null_value = _value_to_column(null_value)
                if null_value in params:
                    null_in_condition = True
                elif null_in_condition:
                    params = (*params, null_value)

            sql = None
            if params:
                if len(params) > IN_TO_ANY_THRESHOLD:
                    anyall = "= ANY(%s)" if operator == "in" else "!= ALL(%s)"
                    sql = SQL(f"%s {anyall}", sql_field, list(params))
                else:
                    sql = SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], params)

            if (operator == "in") == null_in_condition:
                if not can_be_null:
                    return sql or SQL("FALSE")
                sql_null = SQL("%s IS NULL", sql_field)
                return SQL("(%s OR %s)", sql, sql_null) if sql else sql_null

            elif operator == "not in" and null_in_condition and not sql:
                return SQL("%s IS NOT NULL", sql_field) if can_be_null else SQL("TRUE")

            assert sql, f"Missing sql query for {operator} {value!r}"
            return sql

        if operator.endswith("like"):
            sql_left = sql_field if self.is_text else SQL("%s::text", sql_field)

            need_wildcard = "=" not in operator
            if need_wildcard:
                sql_value = SQL("%s", f"%{value}%")
            else:
                sql_value = SQL("%s", str(value))
            if operator.endswith("ilike"):
                sql_left = model.env.registry.unaccent(sql_left)
                sql_value = model.env.registry.unaccent(sql_value)

            sql = SQL("%s%s%s", sql_left, SQL_OPERATORS[operator], sql_value)
            if operator in Domain.NEGATIVE_OPERATORS and can_be_null:
                sql = SQL("(%s OR %s IS NULL)", sql, sql_field)
            return sql

        if operator in (">", "<", ">=", "<="):
            accept_null_value = False
            if (null_value := self.falsy_value) is not None:
                value = self._inequality_comparand(value, model)
                accept_null_value = can_be_null and PYTHON_INEQUALITY_OPERATOR[
                    operator
                ](null_value, value)
            sql_value = SQL("%s", _value_to_column(value))

            sql = SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], sql_value)
            if accept_null_value:
                sql = SQL("(%s OR %s IS NULL)", sql, sql_field)
            return sql

        if operator in ("any!", "not any!"):
            if isinstance(value, Query):
                subselect = value.subselect()
            elif isinstance(value, SQL):
                subselect = SQL("(%s)", value)
            else:
                raise TypeError(
                    f"condition_to_sql() operator 'any!' accepts SQL or Query, got {value}"
                )
            sql_operator = SQL_OPERATORS["in" if operator == "any!" else "not in"]
            return SQL("%s%s%s", sql_field, sql_operator, subselect)

        raise NotImplementedError(
            f"Invalid operator {operator!r} for SQL in domain term {(field_expr, operator, value)!r}"
        )

    def _condition_to_sql_company(
        self,
        sql_expr: SQL,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        """Add a NOT NULL guard on company-dependent fields to use the index."""
        if (
            self.company_dependent
            and self.index == "btree_not_null"
            and not (self.type in ("datetime", "date") and field_expr != self.name)
            and model.env["ir.default"]._evaluate_condition_with_fallback(
                model._name, field_expr, operator, value
            )
            is False
        ):
            return SQL(
                "(%s IS NOT NULL AND %s)",
                SQL.identifier(alias, self.name),
                sql_expr,
            )
        return sql_expr

    def expression_getter(self, field_expr: str) -> Callable[[BaseModel], typing.Any]:
        """Given some field expression (what you find in domain conditions),
        return a function that returns the corresponding expression for a record::

            field = record._fields["create_date"]
            get_value = field.expression_getter("create_date.month_number")
            month_number = get_value(record)
        """
        if field_expr == self.name:
            return self.__get__
        raise ValueError(f"Expression not supported on {self}: {field_expr!r}")

    def filter_function(
        self, records: M, field_expr: str, operator: str, value: typing.Any
    ) -> Callable[[M], bool]:
        assert operator not in Domain.NEGATIVE_OPERATORS, (
            "only positive operators are implemented"
        )
        getter = self.expression_getter(field_expr)

        if operator == "in":
            assert isinstance(value, COLLECTION_TYPES) and value, (
                f"filter_function() 'in' operator expects a collection, not a {type(value)}"
            )
            if not isinstance(value, AbstractSet):
                value = set(value)
            if False in value or self.falsy_value in value:
                if len(value) == 1:
                    return lambda rec: not getter(rec)
                return lambda rec: (val := getter(rec)) in value or not val
            return lambda rec: getter(rec) in value

        if operator.endswith("like"):
            if operator.endswith("ilike"):
                unaccent_python = records.env.registry.unaccent_python

                def unaccent(x):
                    # SQL folds as ``unaccent(...) ILIKE unaccent(...)``, i.e.
                    # case *after* transliteration.  Lowering first hides every
                    # rule whose replacement is upper-case (``₹``->``Rs``,
                    # ``Æ``->``AE``), which is 95 of 9978 characters.
                    return unaccent_python(str(x)).lower() if x else ""

            else:

                def unaccent(x):
                    return str(x) if x else ""

            def build_like_regex(value: str, exact: bool):
                yield "^" if exact else ".*"
                escaped = False
                for char in value:
                    if escaped:
                        escaped = False
                        yield re.escape(char)
                    elif char == "\\":
                        escaped = True
                    elif char == "%":
                        yield ".*"
                    elif char == "_":
                        yield "."
                    else:
                        yield re.escape(char)
                if exact:
                    yield "$"

            like_regex = re.compile(
                "".join(build_like_regex(unaccent(value), "=" in operator)),
                flags=re.DOTALL,
            )
            return lambda rec: like_regex.match(unaccent(getter(rec)))

        if pyop := PYTHON_INEQUALITY_OPERATOR.get(operator):
            can_be_null = False
            if (null_value := self.falsy_value) is not None:
                value = self._inequality_comparand(value, records)
                can_be_null = pyop(null_value, value)

            def check_inequality(rec):
                rec_value = getter(rec)
                try:
                    if rec_value is False or rec_value is None:
                        return can_be_null
                    return pyop(rec_value, value)
                except ValueError, TypeError:
                    return False

            return check_inequality

        raise NotImplementedError(f"Invalid simple operator {operator!r}")
