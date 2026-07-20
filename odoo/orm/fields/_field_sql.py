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
    from .._typing import BaseModel

    M = typing.TypeVar("M", bound=BaseModel)


# Maps domain inequality operators to their Python callables (used to filter
# in-memory recordsets without a SQL round-trip). Moved here with the SQL methods
# that use it (formerly in base.py).
PYTHON_INEQUALITY_OPERATOR: dict[str, Callable[[object, object], bool]] = {
    "<": pyoperator.lt,
    ">": pyoperator.gt,
    "<=": pyoperator.le,
    ">=": pyoperator.ge,
}

# Above this many values, an ``in``/``not in`` condition is emitted as
# ``= ANY(%s)`` / ``!= ALL(%s)`` (one array parameter) instead of
# ``IN (%s, %s, ...)`` (one bound parameter per value). ``IN <tuple>`` makes
# psycopg parse a query string growing O(N): a 1k/10k-row multi-column read
# measured ~48% faster end-to-end with ANY, and a 10k-id ``browse().read()``
# otherwise builds a ~40 KB statement. The win is concentrated at large N
# (sub-0.1 ms below ~100 values), so small conditions keep plain ``IN``: no
# measurable benefit, and it keeps the size-invariant canonical SQL the
# test-suite asserts.
IN_TO_ANY_THRESHOLD = 100


class _FieldSqlMixin(_FieldStubs):
    """SQL and domain-condition generation for a field."""

    def to_sql(self, model: BaseModel, alias: str) -> SQL:
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
            # in _read_group_orderby the result of field to sql will be mogrified and split to
            # e.g SQL('COALESCE(%s->%s') and SQL('to_jsonb(%s))::boolean') as 2 orderby values
            # and concatenated by SQL(',') in the final result, which works in an unexpected way
            sql_field = SQL(
                "COALESCE(%(column)s->%(company_id)s,to_jsonb(%(fallback)s::%(column_type)s))",
                column=sql_field,
                company_id=str(model.env.company.id),
                fallback=fallback,
                column_type=SQL(self._column_type[1]),
            )
            if self.type in ("boolean", "integer", "float", "monetary"):
                return SQL("(%s)::%s", sql_field, SQL(self._column_type[1]))
            # here the specified value for a company might be NULL e.g. '{"1": null}'::jsonb
            # the result of current sql_field might be 'null'::jsonb
            # ('null'::jsonb)::text == 'null'
            # ('null'::jsonb->>0)::text IS NULL
            return SQL("(%s->>0)::%s", sql_field, SQL(self._column_type[1]))

        return sql_field

    def property_to_sql(
        self,
        field_sql: SQL,
        property_name: str,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        """Return an :class:`SQL` object that represents the value of the given
        expression from the given table alias.

        The query object is necessary for fields that need to add tables to the query.
        """
        raise ValueError(f"Invalid field property {property_name!r} on {self}")

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
                return self.convert_to_column(v, model, validate=False)

        else:
            # reading a property, keep value as-is
            def _value_to_column(v: typing.Any) -> typing.Any:
                return v

        # support for SQL value
        if operator in SQL_OPERATORS and isinstance(value, SQL):
            warnings.warn(
                "Since 19.0, use Domain.custom(to_sql=lambda model, alias, query: SQL(...))",
                DeprecationWarning,
                stacklevel=2,
            )
            return SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], value)

        # nullability
        can_be_null = self not in model.env.registry.not_null_fields

        # operator: in (equality)
        if operator in ("in", "not in"):
            assert isinstance(value, COLLECTION_TYPES), (
                f"condition_to_sql() 'in' operator expects a collection, not a {value!r}"
            )
            params = tuple(
                _value_to_column(v) for v in value if v is not False and v is not None
            )
            null_in_condition = len(params) < len(value)
            # if we have a value treated as null
            if (null_value := self.falsy_value) is not None:
                null_value = _value_to_column(null_value)
                if null_value in params:
                    null_in_condition = True
                elif null_in_condition:
                    params = (*params, null_value)

            sql = None
            if params:
                if len(params) > IN_TO_ANY_THRESHOLD:
                    # Large list: a single array parameter keeps the SQL
                    # constant-size (see IN_TO_ANY_THRESHOLD).  ``params`` never
                    # contains NULL (False/None filtered above), so
                    # ``= ANY``/``!= ALL`` match ``IN``/``NOT IN`` exactly.
                    anyall = "= ANY(%s)" if operator == "in" else "!= ALL(%s)"
                    sql = SQL(f"%s {anyall}", sql_field, list(params))
                else:
                    sql = SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], params)

            if (operator == "in") == null_in_condition:
                # field in {val, False} => field IN vals OR field IS NULL
                # field not in {val} => field NOT IN vals OR field IS NULL
                if not can_be_null:
                    return sql or SQL("FALSE")
                sql_null = SQL("%s IS NULL", sql_field)
                return SQL("(%s OR %s)", sql, sql_null) if sql else sql_null

            elif operator == "not in" and null_in_condition and not sql:
                # if we have a base query, null values are already exluded
                return SQL("%s IS NOT NULL", sql_field) if can_be_null else SQL("TRUE")

            assert sql, f"Missing sql query for {operator} {value!r}"
            return sql

        # operator: like
        if operator.endswith("like"):
            # cast value to text for any like comparison
            sql_left = sql_field if self.is_text else SQL("%s::text", sql_field)

            # add wildcard and unaccent depending on the operator
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

        # operator: inequality
        if operator in (">", "<", ">=", "<="):
            accept_null_value = False
            if (null_value := self.falsy_value) is not None:
                value = self.convert_to_cache(value, model) or null_value
                accept_null_value = can_be_null and PYTHON_INEQUALITY_OPERATOR[
                    operator
                ](null_value, value)
            sql_value = SQL("%s", _value_to_column(value))

            sql = SQL("%s%s%s", sql_field, SQL_OPERATORS[operator], sql_value)
            if accept_null_value:
                sql = SQL("(%s OR %s IS NULL)", sql, sql_field)
            return sql

        # operator: any
        # relational operators override this for more specific behaviour; here we
        # just check the field against the subselect, e.g. ('id', 'any!', Query|SQL)
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
            and not (
                self.type in ("datetime", "date") and field_expr != self.name
            )  # READ_GROUP_NUMBER_GRANULARITY is not supported
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

        # operator: in (equality)
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

        # operator: like
        if operator.endswith("like"):
            # we may get a value which is not a string
            if operator.endswith("ilike"):
                # ilike uses unaccent and lower-case comparison
                unaccent_python = records.env.registry.unaccent_python

                def unaccent(x):
                    return unaccent_python(str(x).lower()) if x else ""

            else:

                def unaccent(x):
                    return str(x) if x else ""

            # build a regex matching the SQL-like expression ('\' escapes in SQL)
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
                # no need to match r'.*' in else because we only use .match()

            like_regex = re.compile(
                "".join(build_like_regex(unaccent(value), "=" in operator)),
                flags=re.DOTALL,
            )
            return lambda rec: like_regex.match(unaccent(getter(rec)))

        # operator: inequality
        if pyop := PYTHON_INEQUALITY_OPERATOR.get(operator):
            can_be_null = False
            if (null_value := self.falsy_value) is not None:
                value = value or null_value
                can_be_null = pyop(null_value, value)

            def check_inequality(rec):
                rec_value = getter(rec)
                try:
                    if rec_value is False or rec_value is None:
                        return can_be_null
                    return pyop(rec_value, value)
                except (ValueError, TypeError):
                    # ignoring error, type mismatch
                    return False

            return check_inequality

        raise NotImplementedError(f"Invalid simple operator {operator!r}")
