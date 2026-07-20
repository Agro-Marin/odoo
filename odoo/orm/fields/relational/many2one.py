import typing
from collections.abc import (
    Iterator,
    Reversible,
)
from typing import override

from odoo.exceptions import AccessError, MissingError
from odoo.libs._field_access import scalar_cache_get as _scalar_cache_get
from odoo.tools import SQL, Query, unique
from odoo.tools.misc import PENDING, SENTINEL, Sentinel

from ..._recordset import is_recordset
from ...domain import Domain
from ...primitives import Command, NewId
from ..base import IR_MODELS, Field
from ._base import _Relational

if typing.TYPE_CHECKING:

    from ...models import BaseModel

    OnDelete = typing.Literal["cascade", "set null", "restrict"]


class Many2one(_Relational):
    """The value of such a field is a recordset of size 0 (no
    record) or 1 (a single record).

    :param str comodel_name: name of the target model
        ``Mandatory`` except for related or extended fields.

    :param domain: an optional domain to set on candidate values on the
        client side (domain or a python expression that will be evaluated
        to provide domain)

    :param dict context: an optional context to use on the client side when
        handling that field

    :param str ondelete: what to do when the referred record is deleted;
        possible values are: ``'set null'``, ``'restrict'``, ``'cascade'``

    :param bool bypass_search_access: whether access rights are bypassed on the
        comodel (default: ``False``)

    :param bool delegate: set it to ``True`` to make fields of the target model
        accessible from the current model (corresponds to ``_inherits``)

    :param bool check_company: Mark the field to be verified in
        :meth:`~odoo.models.Model._check_company`. Has a different behaviour
        depending on whether the field is company_dependent or not.
        Constrains non-company-dependent fields to target records whose
        company_id(s) are compatible with the record's company_id(s).
        Constrains company_dependent fields to target records whose
        company_id(s) are compatible with the currently active company.
    """

    type = "many2one"
    _column_type = ("int4", "int4")

    ondelete: OnDelete | None = None  # what to do when value is deleted
    delegate: bool = False  # whether self implements delegation

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
            # multi-record or empty: delegate to the _Relational batch path,
            # which performs the access check and pending guard itself.
            return super().__get__(record, owner)
        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")
        if self.is_stored_computed and env._core.has_pending_field(self):
            self.recompute(record)
        value = _scalar_cache_get(env.__dict__, self, ids[0], PENDING, SENTINEL)
        if value is not SENTINEL:
            # inlined convert_to_record (singleton fast path)
            rs = object.__new__(record.pool[self.comodel_name])
            rs.env = env
            rs._ids = () if value is None else (value,)
            rs._prefetch_ids = PrefetchMany2one(record, self)
            return rs
        # cache miss: full Field.__get__ triggers a DB fetch
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
        # determine self.delegate
        if name in model_class._inherits.values():
            self.delegate = True
            # self.delegate implies self.bypass_search_access
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
        # ondelete: assign a default if unset; 'set null' on a required m2o
        # below is rejected as a programming error.
        if not self.ondelete:
            comodel = model.env[self.comodel_name]
            if model.is_transient() and not comodel.is_transient():
                # m2o from a TransientModel can block deletion via foreign keys,
                # so default to 'cascade' unless stated otherwise.
                self.ondelete = "cascade" if self.required else "set null"
            else:
                self.ondelete = "restrict" if self.required else "set null"
        if self.ondelete == "set null" and self.required:
            raise ValueError(
                f"The m2o field {self.name} of model {model._name} is required but declares its ondelete policy "
                "as being 'set null'. Only 'restrict' and 'cascade' make sense."
            )
        if self.ondelete == "restrict" and self.comodel_name in IR_MODELS:
            raise ValueError(
                f"Field {self.name} of model {model._name} is defined as ondelete='restrict' "
                f"while having {self.comodel_name} as comodel, the 'restrict' mode is not "
                f"supported for this type of field as comodel."
            )

    @override
    def update_db(
        self, model: BaseModel, columns: dict[str, dict[str, typing.Any]]
    ) -> bool:
        comodel = model.env[self.comodel_name]
        if not model.is_transient() and comodel.is_transient():
            raise ValueError(
                f"Many2one {self} from Model to TransientModel is forbidden"
            )
        return super().update_db(model, columns)

    @override
    def update_db_column(self, model: BaseModel, column: dict[str, typing.Any]) -> None:
        super().update_db_column(model, column)
        model.pool.post_init(self.update_db_foreign_key, model, column)

    def update_db_foreign_key(
        self, model: BaseModel, column: dict[str, typing.Any]
    ) -> None:
        if self.company_dependent:
            return
        comodel = model.env[self.comodel_name]
        # foreign keys don't work on views, and custom models may be sql views
        if not model._is_an_ordinary_table() or not comodel._is_an_ordinary_table():
            return
        # ir_actions is inherited, so foreign key doesn't work on it
        if not comodel._auto or comodel._table == "ir_actions":
            return
        # create/update the foreign key, and reflect it in 'ir.model.constraint'
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
        record: BaseModel,
        values: dict | None = None,
        validate: bool = True,
    ) -> int | None:
        return value or None

    @override
    def convert_to_cache(
        self, value: typing.Any, record: BaseModel, validate: bool = True
    ) -> int | NewId | None:
        # cache format: id or None
        if type(value) is int or type(value) is NewId:
            id_ = value
        elif is_recordset(value):
            if validate and (value._name != self.comodel_name or len(value) > 1):
                raise ValueError(f"Wrong value for {self}: {value!r}")
            id_ = value._ids[0] if value._ids else None
        elif isinstance(value, tuple):
            # value is a pair (id, name) or a tuple of ids. Reject x2many Command
            # tuples: they would degrade to ``id_ = command_int`` and silently
            # corrupt the m2o.
            if validate:
                self._reject_command_tuple(value)
            # normalise falsy ids to None: web clients send (False, "") for "no
            # value". A literal False/0 would yield _ids=(False,) with len()==1
            # but bool()==False, an inconsistent recordset.
            id_ = (value[0] or None) if value else None
        elif isinstance(value, dict):
            # return a new record (with the given field 'id' as origin)
            comodel = record.env[self.comodel_name]
            origin = comodel.browse(value.get("id"))
            id_ = comodel.new(value, origin=origin).id
        else:
            id_ = None

        if self.delegate and record and not any(record._ids):
            # if all records are new, then so is the parent
            id_ = id_ and NewId(id_)

        return id_

    @override
    def convert_to_record(
        self, value: int | NewId | None, record: BaseModel
    ) -> BaseModel:
        # use registry directly; object.__new__ bypasses type.__call__ dispatch
        rs = object.__new__(record.pool[self.comodel_name])
        rs.env = record.env
        rs._ids = () if value is None else (value,)
        rs._prefetch_ids = PrefetchMany2one(record, self)
        return rs

    def convert_to_record_multi(
        self, values: list[int | NewId | None], records: BaseModel
    ) -> BaseModel:
        # return the ids as a recordset without duplicates
        rs = object.__new__(records.pool[self.comodel_name])
        rs.env = records.env
        rs._ids = tuple(unique(id_ for id_ in values if id_ is not None))
        rs._prefetch_ids = PrefetchMany2one(records, self)
        return rs

    @override
    def convert_to_read(
        self,
        value: BaseModel,
        record: BaseModel,
        use_display_name: bool = True,
    ) -> int | tuple[int, str] | typing.Literal[False]:
        if use_display_name and value:
            # display_name as superuser: visibility of the m2o value (id and
            # name) depends on the current record's access rights, not the
            # value's.
            try:
                # value.sudo() prefetches the same records as value
                return (value.id, value.sudo().display_name)
            except MissingError:
                # should not happen unless the foreign key is missing
                return False
        else:
            return value.id

    @override
    def convert_to_write(
        self, value: typing.Any, record: BaseModel
    ) -> int | NewId | typing.Literal[False]:
        if type(value) is int or type(value) is NewId:
            return value
        if not value:
            return False
        if is_recordset(value) and value._name == self.comodel_name:
            return value.id
        if isinstance(value, tuple):
            # value is either a pair (id, name), or a tuple of ids
            self._reject_command_tuple(value)
            return value[0] if value else False
        if isinstance(value, dict):
            return record.env[self.comodel_name].new(value).id
        raise ValueError(f"Wrong value for {self}: {value!r}")

    def _reject_command_tuple(self, value: tuple) -> None:
        """Raise if ``value`` is an x2many ``Command`` tuple.

        A ``(command, id, values)`` triple assigned to a many2one would silently
        degrade to ``value[0]`` (the command int) and corrupt the field. Guard
        both the cache and write conversion paths identically.
        """
        if len(value) == 3 and isinstance(value[0], int):
            if value[0] in Command._value2member_map_:
                raise ValueError(
                    f"Wrong value for {self}: x2many Command tuple "
                    f"{value!r} cannot be assigned to a many2one field"
                )

    @override
    def convert_to_export(self, value: BaseModel, record: BaseModel) -> str:
        return value.display_name if value else ""

    @override
    def convert_to_display_name(
        self, value: BaseModel, record: BaseModel
    ) -> str | typing.Literal[False]:
        return value.display_name

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        # discard recomputation of self on records
        records.env.remove_to_compute(self, records)

        # discard the records that are not modified
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

        # remove records from the cache of one2many fields of old corecords
        self._remove_inverses(records, cache_value)

        # update the cache of self
        self._update_cache(records, cache_value, dirty=True)

        # update the cache of one2many fields of new corecord
        self._update_inverses(records, cache_value)

    def _remove_inverses(self, records: BaseModel, value: int | NewId | None) -> None:
        """Remove ``records`` from the cached o2m inverse fields of ``self``."""
        inverse_fields = records.pool.field_inverses[self]
        if not inverse_fields:
            return

        record_ids = set(records._ids)
        # align(id) returns a NewId if records are new, a real id otherwise
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
        """Add ``records`` to the cached o2m inverse fields of ``self``."""
        if value is None:
            return
        corecord = self.convert_to_record(value, records)
        for invf in records.pool.field_inverses[self]:
            valid_records = records.filtered_domain(invf.get_comodel_domain(corecord))
            if not valid_records:
                continue
            ids0 = invf._get_cache(corecord.env).get(corecord.id)
            # if the value for the corecord is not in cache, but this is a new
            # record, assign it anyway, as you won't be able to fetch it from
            # database (see `test_sale_order`)
            if ids0 is not None or not corecord.id:
                ids1 = tuple(unique((ids0 or ()) + valid_records._ids))
                invf._update_cache(corecord, ids1)

    @override
    def to_sql(self, model: BaseModel, alias: str) -> SQL:
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
            # non-'any' operators: build the condition from the column type
            return super().condition_to_sql(
                field_expr, operator, value, model, alias, query
            )

        comodel = model.env[self.comodel_name]
        sql_field = model._field_to_sql(alias, field_expr, query)
        can_be_null = self not in model.env.registry.not_null_fields
        bypass_access = operator in ("any!", "not any!") or self.bypass_search_access
        positive = operator in ("any", "any!")

        # decide whether to use a LEFT JOIN
        left_join = bypass_access and isinstance(value, Domain)
        if left_join and not positive:
            # for 'not any!' with mostly positive conditions, NOT IN is better:
            # it has a better chance to use indexes. So prefer LEFT JOIN only
            # when negatives dominate, except when filtering on 'id'.
            #   `field NOT IN (SELECT ... WHERE z = y)` better than
            #   `LEFT JOIN ... ON field = id WHERE z <> y`
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

    def join(self, model: BaseModel, alias: str, query: Query) -> tuple[BaseModel, str]:
        """Add a LEFT JOIN to ``query`` by following field ``self``,
        and return the joined table's corresponding model and alias.
        """
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
    """Iterable over a many2one's values across a record's prefetch set."""

    __slots__ = ("field", "record")

    def __init__(self, record: BaseModel, field: Many2one) -> None:
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
