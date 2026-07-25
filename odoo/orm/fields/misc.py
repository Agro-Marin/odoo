import typing
from typing import override

from psycopg.types.json import Json as PsycopgJson

from odoo.libs.json import dumps as _fast_dumps
from odoo.libs.json import fast_clone
from odoo.libs.json import loads as _fast_loads
from odoo.tools import SQL
from odoo.tools.json import orjson_default

from ..primitives import IdType, NewId
from .base import Field, _make_scalar_get

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import ModelLike
    from ..models import BaseModel


class Boolean(Field[bool]):
    """Encapsulates a :class:`bool`."""

    type = "boolean"
    _column_type = ("bool", "bool")
    falsy_value = False

    if not typing.TYPE_CHECKING:
        # Runtime fast path; the type checker inherits Field[bool].__get__.
        __get__ = _make_scalar_get(lambda v: False if v is None else v)

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> bool:
        return bool(value)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> bool:
        return bool(value)

    @override
    def convert_to_export(self, value: typing.Any, record: ModelLike) -> bool:
        return bool(value)

    def _condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        if operator not in ("in", "not in"):
            return super()._condition_to_sql(
                field_expr, operator, value, model, alias, query
            )

        # get field and check access
        sql_field = model._field_to_sql(alias, field_expr, query)

        # express all conditions as (field_expr, 'in', possible_values)
        possible_values = (
            {bool(v) for v in value}
            if operator == "in"
            else {True, False} - {bool(v) for v in value}  # operator == 'not in'
        )
        if len(possible_values) != 1:
            return SQL("TRUE") if possible_values else SQL("FALSE")
        is_true = True in possible_values
        return (
            SQL("%s IS TRUE", sql_field)
            if is_true
            else SQL("%s IS NOT TRUE", sql_field)
        )


class Json(Field):
    """Store unstructured information in a jsonb PostgreSQL column.

    Some features won't be implemented, including:
    * searching
    * indexing
    * mutating the values.
    """

    type = "json"
    _column_type = ("jsonb", "jsonb")

    @override
    def convert_to_record(self, value: typing.Any, record: ModelLike) -> typing.Any:
        """Return a copy of the value"""
        return False if value is None else fast_clone(value)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> typing.Any:
        if not value:
            # Normalize all falsy values (None, False, {}, []) to None;
            # convert_to_record maps None back to False ("no value").
            return None
        return _fast_loads(_fast_dumps(value, default=orjson_default))

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        if validate:
            value = self.convert_to_cache(value, record)
        if value is None:
            return None
        return PsycopgJson(value)

    @override
    def convert_to_export(self, value: typing.Any, record: ModelLike) -> str:
        if not value:
            return ""
        # default=orjson_default (as in convert_to_cache) lets non-native types
        # (date, Decimal) serialise instead of raising.
        return _fast_dumps(value, default=orjson_default)


class Id(Field[IdType | typing.Literal[False]]):
    """Special case for field 'id'."""

    # The value is not necessarily an integer (may be a NewId).
    # ``type`` is "integer" so the client/views see the id column as integer,
    # but Integer owns the "integer" ttype in _by_type__: Id is the magic id
    # column, never instantiated from a DB ttype, so it opts out of registration.
    type = "integer"
    _register_type = False
    column_type = ("int4", "int4")

    string = "ID"
    store = True
    readonly = True
    prefetch = False

    def update_db(self, model: ModelLike, columns: dict[str, typing.Any]) -> None:
        pass  # this column is created with the table

    @typing.overload
    def __get__(self, record: None, owner: typing.Any = None) -> typing.Self: ...
    @typing.overload
    def __get__(
        self, record: BaseModel, owner: typing.Any = None
    ) -> IdType | typing.Literal[False]: ...
    @typing.overload
    def __get__(self, record: object, owner: typing.Any = None) -> typing.Any: ...

    @override
    def __get__(
        self, record: typing.Any, owner: typing.Any = None
    ) -> IdType | typing.Literal[False] | typing.Self:
        if record is None:
            return self

        # kept inline for speed: record.id is extremely hot
        ids = record._ids
        size = len(ids)
        if size == 0:
            return False
        elif size == 1:
            return ids[0]
        raise ValueError(f"Expected singleton: {record}")

    @override
    def __set__(self, record: BaseModel, value: typing.Any) -> None:
        msg = "field 'id' cannot be assigned"
        raise TypeError(msg)

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        """Coerce a value to the id column's type, or fail cleanly.

        Upstream returns ``value`` unchanged.  That identity passthrough made
        ``id`` the ONLY field class that let an ill-typed domain comparand reach
        psycopg: every sibling (``Integer.convert_to_column`` is ``int(value or
        0)``, Char/Date/... likewise convert or raise) turns a bad value into a
        clean Python ``ValueError``, but ``('id', '>', x)`` passed ``x`` straight
        through to the driver.  The database then raised -- ``operator does not
        exist: integer > boolean`` for ``False``, ``invalid input syntax for type
        integer`` for ``"abc"``/``[]``, ``integer > bytea`` for bytes -- which
        ABORTS THE TRANSACTION, so a caller that catches the error still loses
        every subsequent query.  Every model has ``id``, so this affected every
        model's ``search()``.

        Validation applies only to ORM-created tables (``_auto``), whose ``id``
        really is ``int4``.  An ``_auto = False`` model builds its own relation
        -- ``test_orm.view.str.id`` is a ``_table_query`` view whose id column is
        *text* -- so there the value passes through untouched, exactly as before.

        On a real table, conversions are chosen to preserve every previously
        working call:

        * ``False``/``None`` -> ``None`` (SQL NULL).  ``id`` is ``NOT NULL`` and
          always positive, so an unset comparand can only mean "no value"; the
          domain optimizer collapses that shape to the FALSE domain before it
          ever gets here (see ``_optimize_inequality_against_null``).
        * ``int``/``float`` pass through UNCHANGED -- notably floats are *not*
          truncated, because ``id >= 1.5`` and ``id >= 1`` select different rows.
        * ``str`` is parsed as an integer, matching what Postgres already did
          implicitly for ``('id', '>', "123")``.
        * anything else raises ``ValueError`` naming the field -- a clean,
          catchable error that leaves the transaction usable.

        ``NewId`` always passes through: an in-memory id reaching SQL is a
        caller-side bug, and this method is not the place to re-diagnose it.
        """
        if value is None or value is False:
            return None
        if isinstance(value, NewId):
            return value
        # A model that manages its own relation (_auto = False, e.g. a
        # _table_query SQL view) may key on any column type, so nothing here can
        # be assumed about it -- keep upstream's passthrough.
        if not record._auto:
            return value
        # bool is a subclass of int; True is not a record id.
        if value is True:
            raise ValueError(f"Invalid id value for {self}: {value!r}")
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                raise ValueError(f"Invalid id value for {self}: {value!r}") from None
        raise ValueError(f"Invalid id value for {self}: {value!r}")

    def to_sql(self, model: ModelLike, alias: str) -> SQL:
        # do not flush; id is never flushed, just return the identifier
        assert self.store, "id field must be stored"
        return SQL.identifier(alias, self.name)

    def expression_getter(self, field_expr: str) -> typing.Any:
        if field_expr != "id.origin":
            return super().expression_getter(field_expr)

        def getter(record: BaseModel) -> typing.Any:
            # guard the empty recordset (upstream returned False, not IndexError)
            ids = record._ids
            if not ids:
                return False
            return (id_ := ids[0]) or getattr(id_, "origin", None) or False

        return getter
