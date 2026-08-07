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
from odoo.tools.misc import PENDING, SENTINEL

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
    def to_sql(self, model: ModelLike, alias: str) -> SQL:
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
        raise ValueError(f"Invalid field property {property_name!r} on {self}")

    def _comparand_to_column(self, value: typing.Any, model: BaseModel) -> typing.Any:
        return self.convert_to_column(value, model, validate=False)

    def _inequality_comparand(self, value: typing.Any, model: BaseModel) -> typing.Any:
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
        if field_expr == self.name:
            return self.__get__
        raise ValueError(f"Expression not supported on {self}: {field_expr!r}")

    def _pattern_text(self, cache_value: typing.Any) -> str:
        if cache_value is None or cache_value is False:
            return ""
        return str(cache_value)

    def _pattern_getter(
        self, records: M, field_expr: str, getter: Callable[[M], typing.Any]
    ) -> Callable[[M], str]:
        pattern_text = self._pattern_text
        if field_expr != self.name or callable(self.translate):
            return lambda rec: pattern_text(getter(rec))

        env = records.env
        _MISSING = SENTINEL
        _PENDING = PENDING
        get_cache = self._get_cache

        def render(rec: M) -> str:
            value = get_cache(env).get(rec._ids[0], _MISSING)
            if value is _MISSING or value is _PENDING:
                record_value = getter(rec)
                value = get_cache(env).get(rec._ids[0], _MISSING)
                if value is _MISSING:
                    return pattern_text(record_value)
            return pattern_text(value)

        return render

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
                    return unaccent_python(x).lower()

            else:

                def unaccent(x):
                    return x

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

            pattern = value if isinstance(value, str) else self._pattern_text(value)
            like_regex = re.compile(
                "".join(build_like_regex(unaccent(pattern), "=" in operator)),
                flags=re.DOTALL,
            )
            render = self._pattern_getter(records, field_expr, getter)
            return lambda rec: like_regex.match(unaccent(render(rec)))

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
