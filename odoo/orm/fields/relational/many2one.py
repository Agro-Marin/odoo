import typing
from collections.abc import (
    Iterator,
    Reversible,
)
from typing import override

from odoo.exceptions import AccessError, MissingError
from odoo.tools import SQL, Query, unique
from odoo.tools.misc import PENDING, SENTINEL, Sentinel

from ..._recordset import is_recordset
from ...domain import Domain
from ...primitives import Command, NewId
from ..base import Field
from ._base import _Relational

if typing.TYPE_CHECKING:
    from ..._typing import ModelLike
    from ...models import BaseModel

    OnDelete = typing.Literal["cascade", "set null", "restrict"]


class Many2one(_Relational):
    type = "many2one"
    _column_type = ("int4", "int4")

    ondelete: OnDelete | None = None
    delegate: bool = False

    @property
    def is_delegating(self) -> bool:
        """See :attr:`Field.is_delegating`."""
        return self.delegate

    @typing.overload
    def __get__(self, record: None, owner: typing.Any = None) -> typing.Self: ...
    @typing.overload
    def __get__(self, record: BaseModel, owner: typing.Any = None) -> BaseModel: ...
    @typing.overload
    def __get__(self, record: object, owner: typing.Any = None) -> typing.Any: ...

    @override
    def __get__(
        self, record: typing.Any, owner: typing.Any = None
    ) -> BaseModel | typing.Self:
        if record is None:
            return self
        ids = record._ids
        if len(ids) != 1:
            return super().__get__(record, owner)
        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")
        if self.is_stored_computed and env._core.has_pending_field(self):
            self.recompute(record)
        try:
            value = env.__dict__["_field_cache_memo"][self][ids[0]]
        except KeyError:
            pass
        else:
            if value is not PENDING:
                rs = object.__new__(record.pool[self.comodel_name])
                rs.env = env
                rs._ids = () if value is None else (value,)
                rs._prefetch_ids = PrefetchMany2one(record, self)
                return rs
        return Field.__get__(self, record, owner)

    def __init__(
        self,
        comodel_name: str | Sentinel = SENTINEL,
        string: str | Sentinel = SENTINEL,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(comodel_name=comodel_name, string=string, **kwargs)

    @override
    def _setup_attrs__(self, model_class: type[BaseModel], name: str) -> None:
        super()._setup_attrs__(model_class, name)
        if name in model_class._inherits.values():
            self.delegate = True
            self.bypass_search_access = True
        elif self.delegate:
            comodel_name = self.comodel_name or "comodel_name"
            raise TypeError(
                f"The delegate field {self} must be declared in the model class e.g.\n"
                f"_inherits = {{{comodel_name!r}: {name!r}}}"
            )

    @override
    def setup_nonrelated(self, model: BaseModel) -> None:
        super().setup_nonrelated(model)
        if not self.ondelete:
            comodel = model.env[self.comodel_name]
            if model.is_transient() and not comodel.is_transient():
                self.ondelete = "cascade" if self.required else "set null"
            else:
                self.ondelete = "restrict" if self.required else "set null"
        if self.ondelete == "set null" and self.required:
            raise ValueError(
                f"The m2o field {self.name} of model {model._name} is required but declares its ondelete policy "
                "as being 'set null'. Only 'restrict' and 'cascade' make sense."
            )
        if (
            self.ondelete == "restrict"
            and model.env[self.comodel_name]._is_registry_metadata
        ):
            raise ValueError(
                f"Field {self.name} of model {model._name} is defined as ondelete='restrict' "
                f"while having {self.comodel_name} as comodel, the 'restrict' mode is not "
                f"supported for this type of field as comodel."
            )

    @override
    def update_db(
        self, model: ModelLike, columns: dict[str, dict[str, typing.Any]]
    ) -> bool:
        comodel = model.env[self.comodel_name]
        if not model.is_transient() and comodel.is_transient():
            raise ValueError(
                f"Many2one {self} from Model to TransientModel is forbidden"
            )
        return super().update_db(model, columns)

    @override
    def update_db_column(self, model: ModelLike, column: dict[str, typing.Any]) -> None:
        super().update_db_column(model, column)
        model.pool.post_init(self.update_db_foreign_key, model, column)

    def update_db_foreign_key(
        self, model: BaseModel, column: dict[str, typing.Any]
    ) -> None:
        if self.company_dependent:
            return
        comodel = model.env[self.comodel_name]
        if not model._is_an_ordinary_table() or not comodel._is_an_ordinary_table():
            return
        if not comodel._auto or comodel._is_table_inheritance_root():
            return
        model.pool.add_foreign_key(
            model._table,
            self.name,
            comodel._table,
            "id",
            self.ondelete or "set null",
            model,
            self._module,
        )

    @override
    def _update_inverse(self, records: BaseModel, value: BaseModel) -> None:
        for record in records:
            self._update_cache(
                record, self.convert_to_cache(value, record, validate=False)
            )

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict | None = None,
        validate: bool = True,
    ) -> int | None:
        return value or None

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> int | NewId | None:
        if type(value) is int or type(value) is NewId:
            id_ = value
        elif is_recordset(value):
            if validate and (value._name != self.comodel_name or len(value) > 1):
                raise ValueError(f"Wrong value for {self}: {value!r}")
            id_ = value._ids[0] if value._ids else None
        elif isinstance(value, tuple):
            if validate:
                self._reject_command_tuple(value)
            id_ = (value[0] or None) if value else None
        elif isinstance(value, dict):
            comodel = record.env[self.comodel_name]
            origin = comodel.browse(value.get("id"))
            id_ = comodel.new(value, origin=origin).id
        elif validate and value:
            raise ValueError(f"Wrong value for {self}: {value!r}")
        else:
            id_ = None

        if self.delegate and record and not any(record._ids):
            id_ = id_ and NewId(id_)

        return id_

    @override
    def convert_to_record(
        self, value: int | NewId | None, record: ModelLike
    ) -> BaseModel:
        rs = object.__new__(record.pool[self.comodel_name])
        rs.env = record.env
        rs._ids = () if value is None else (value,)
        rs._prefetch_ids = PrefetchMany2one(record, self)
        return rs

    def convert_to_record_multi(
        self, values: list[int | NewId | None], records: BaseModel
    ) -> BaseModel:
        rs = object.__new__(records.pool[self.comodel_name])
        rs.env = records.env
        rs._ids = tuple(unique(id_ for id_ in values if id_ is not None))
        rs._prefetch_ids = PrefetchMany2one(records, self)
        return rs

    @override
    def convert_to_read(
        self,
        value: BaseModel,
        record: ModelLike,
        use_display_name: bool = True,
    ) -> int | tuple[int, str] | typing.Literal[False]:
        return self.convert_to_read_multi([value], record, use_display_name)[0]

    def convert_to_read_multi(
        self,
        values: list[BaseModel],
        records: ModelLike,
        use_display_name: bool = True,
    ) -> list[typing.Any]:
        if not use_display_name:
            return [value.id for value in values]

        allowed_ids: set | None = None
        if target_ids := list(unique(value.id for value in values if value)):
            targets = records.env[self.comodel_name].browse(target_ids)
            try:
                allowed_ids = set(targets._filtered_access("read")._ids)
            except MissingError:
                allowed_ids = None

        result: list[typing.Any] = []
        for value in values:
            if not value:
                result.append(False)
                continue
            try:
                readable = (
                    value.id in allowed_ids
                    if allowed_ids is not None
                    else bool(value._filtered_access("read"))
                )
                result.append(
                    (value.id, value.sudo().display_name) if readable else False
                )
            except MissingError:
                result.append(False)
        return result

    @override
    def convert_to_write(
        self, value: typing.Any, record: ModelLike
    ) -> int | NewId | typing.Literal[False]:
        if type(value) is int or type(value) is NewId:
            return value
        if not value:
            return False
        if is_recordset(value) and value._name == self.comodel_name:
            return value.id
        if isinstance(value, tuple):
            self._reject_command_tuple(value)
            return value[0] if value else False
        if isinstance(value, dict):
            return record.env[self.comodel_name].new(value).id
        raise ValueError(f"Wrong value for {self}: {value!r}")

    def _reject_command_tuple(self, value: tuple) -> None:
        if len(value) == 3 and isinstance(value[0], int):
            if value[0] in Command._value2member_map_:
                raise ValueError(
                    f"Wrong value for {self}: x2many Command tuple "
                    f"{value!r} cannot be assigned to a many2one field"
                )

    @override
    def convert_to_export(self, value: BaseModel, record: ModelLike) -> str:
        return value.display_name if value else ""

    @override
    def convert_to_display_name(
        self, value: BaseModel, record: ModelLike
    ) -> str | typing.Literal[False]:
        return value.display_name

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        records.env.remove_to_compute(self, records)

        cache_value = self.convert_to_cache(value, records)

        if self.bypass_search_access and not records.env.su:
            try:
                records.env[self.comodel_name].browse(cache_value).check_access("read")
            except AccessError as e:
                raise AccessError(
                    records.env._("Failed to write field %s", self) + "\n" + str(e)
                ) from e

        records = self._filter_not_equal(records, cache_value)
        if not records:
            return

        self._remove_inverses(records)

        self._update_cache(records, cache_value, dirty=True)

        self._update_inverses(records, cache_value)

    def _remove_inverses(self, records: BaseModel) -> None:
        inverse_fields = records.pool.field_inverses[self]
        if not inverse_fields:
            return

        record_ids = set(records._ids)
        align = (
            (lambda id_: id_) if all(record_ids) else (lambda id_: id_ and NewId(id_))
        )
        field_cache = self._get_cache(records.env)
        _pending = PENDING
        corecords = records.env[self.comodel_name].browse(
            align(coid)
            for record_id in records._ids
            if (coid := field_cache.get(record_id)) is not None and coid is not _pending
        )

        for invf in inverse_fields:
            inv_cache = invf._get_cache(corecords.env)
            for corecord in corecords:
                ids0 = inv_cache.get(corecord.id)
                if ids0 is not None:
                    ids1 = tuple(id_ for id_ in ids0 if id_ not in record_ids)
                    invf._update_cache(corecord, ids1)

    def _update_inverses(self, records: BaseModel, value: int | NewId | None) -> None:
        if value is None:
            return
        corecord = self.convert_to_record(value, records)
        for invf in records.pool.field_inverses[self]:
            valid_records = records.filtered_domain(invf.get_comodel_domain(corecord))
            if not valid_records:
                continue
            ids0 = invf._get_cache(corecord.env).get(corecord.id)
            if ids0 is not None or not corecord.id:
                ids1 = tuple(unique((ids0 or ()) + valid_records._ids))
                invf._update_cache(corecord, ids1)

    @override
    def to_sql(self, model: ModelLike, alias: str) -> SQL:
        sql_field = super().to_sql(model, alias)
        if self.company_dependent:
            comodel = model.env[self.comodel_name]
            sql_field = SQL(
                """(SELECT %(cotable_alias)s.id
                    FROM %(cotable)s AS %(cotable_alias)s
                    WHERE %(cotable_alias)s.id = %(ref)s)""",
                cotable=SQL.identifier(comodel._table),
                cotable_alias=SQL.identifier(
                    Query.make_alias(comodel._table, "exists")
                ),
                ref=sql_field,
            )
        return sql_field

    @override
    def condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        if (
            operator not in ("any", "not any", "any!", "not any!")
            or field_expr != self.name
        ):
            return super().condition_to_sql(
                field_expr, operator, value, model, alias, query
            )

        comodel = model.env[self.comodel_name]
        sql_field = model._field_to_sql(alias, field_expr, query)
        can_be_null = self not in model.env.registry.not_null_fields
        bypass_access = operator in ("any!", "not any!") or self.bypass_search_access
        positive = operator in ("any", "any!")

        left_join = bypass_access and isinstance(value, Domain)
        if left_join and not positive:
            left_join = sum(
                (-1 if cond.operator in Domain.NEGATIVE_OPERATORS else 1)
                for cond in value.iter_conditions()
            ) < 0 or any(
                cond.field_expr == "id"
                and cond.operator not in Domain.NEGATIVE_OPERATORS
                for cond in value.iter_conditions()
            )

        if left_join:
            comodel, coalias = self.join(model, alias, query)
            if not positive:
                value = (~value).optimize_full(comodel)
            sql = value._to_sql(comodel, coalias, query)
            if self.company_dependent:
                sql = self._condition_to_sql_company(
                    sql, field_expr, operator, value, model, alias, query
                )
            if can_be_null:
                if positive:
                    sql = SQL("(%s IS NOT NULL AND %s)", sql_field, sql)
                else:
                    sql = SQL("(%s IS NULL OR %s)", sql_field, sql)
            return sql

        if isinstance(value, Domain):
            value = comodel._search(
                value, active_test=False, bypass_access=bypass_access
            )
        if isinstance(value, Query):
            subselect = value.subselect()
        elif isinstance(value, SQL):
            subselect = SQL("(%s)", value)
        else:
            raise TypeError(
                f"condition_to_sql() 'any' operator accepts Domain, SQL or Query, got {value}"
            )
        sql = SQL(
            "%s%s%s",
            sql_field,
            SQL(" IN ") if positive else SQL(" NOT IN "),
            subselect,
        )
        if can_be_null and not positive:
            sql = SQL("(%s IS NULL OR %s)", sql_field, sql)
        if self.company_dependent:
            sql = self._condition_to_sql_company(
                sql, field_expr, operator, value, model, alias, query
            )
        return sql

    def join(self, model: ModelLike, alias: str, query: Query) -> tuple[BaseModel, str]:
        comodel = model.env[self.comodel_name]
        coalias = query.make_alias(alias, self.name)
        query.add_join(
            "LEFT JOIN",
            coalias,
            comodel._table,
            SQL(
                "%s = %s",
                model._field_to_sql(alias, self.name, query),
                SQL.identifier(coalias, "id"),
            ),
        )
        return (comodel, coalias)


class PrefetchMany2one(Reversible):
    __slots__ = ("field", "record")

    def __init__(self, record: ModelLike, field: Many2one) -> None:
        self.record = record
        self.field = field

    def __iter__(self) -> Iterator[int | NewId]:
        field_cache = self.field._get_cache(self.record.env)
        _pending = PENDING
        return unique(
            coid
            for id_ in self.record._prefetch_ids
            if (coid := field_cache.get(id_)) is not None and coid is not _pending
        )

    def __reversed__(self) -> Iterator[int | NewId]:
        field_cache = self.field._get_cache(self.record.env)
        _pending = PENDING
        return unique(
            coid
            for id_ in reversed(self.record._prefetch_ids)
            if (coid := field_cache.get(id_)) is not None and coid is not _pending
        )
