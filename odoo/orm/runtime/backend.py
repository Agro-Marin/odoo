from __future__ import annotations

import logging
import os
import typing
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from itertools import batched

from psycopg.types.json import Json, Jsonb

from odoo.exceptions import LockError, UserError
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads
from odoo.libs.profiling import _OrmProfile
from odoo.tools import SQL, OrderedSet, Query, partition
from odoo.tools.translate import _

from ..primitives import (
    MODULE_UNINSTALL_FLAG,
    SQL_DEFAULT,
    UPDATE_BATCH_SIZE,
    NewId,
)

if typing.TYPE_CHECKING:
    from ..components.storage import DictBackend
    from ..domain import Domain
    from ..fields import Field
    from ..models.base import BaseModel

_logger = logging.getLogger("odoo.orm.backend")
_orm_crud = logging.getLogger("odoo.orm.crud")
_orm_read = logging.getLogger("odoo.orm.read")

COPY_THRESHOLD = int(os.environ.get("ODOO_COPY_THRESHOLD", "10"))
COPY_DISABLED = os.environ.get("ODOO_DISABLE_COPY", "").lower() in (
    "1",
    "true",
    "yes",
)

_UNIFORM_UPDATE_TYPES = (
    type(None),
    bool,
    bytes,
    date,
    datetime,
    Decimal,
    float,
    int,
    str,
)


def _unwrap_json(value: typing.Any) -> typing.Any:
    if isinstance(value, (Json, Jsonb)):
        return value.obj
    return value


def _column_read_value(field: Field, value: typing.Any, env) -> typing.Any:
    if (
        field.translate
        and isinstance(value, dict)
        and not env.context.get("prefetch_langs")
    ):
        for lang in field.get_translation_fallback_langs(env):
            scalar = value.get(lang)
            if scalar is not None:
                return scalar
        return None
    return value


@typing.runtime_checkable
class StorageBackend(typing.Protocol):
    supports_parent_store: bool
    supports_record_rules: bool

    supports_joined_m2m_read: bool

    supports_column_scan: bool

    supports_translation_terms: bool

    def create_rows(
        self,
        model: BaseModel,
        stored_list: list[dict[str, typing.Any]],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[int]: ...

    def update_rows(
        self, model: BaseModel, fnames: tuple[str, ...], rows: list[tuple]
    ) -> None: ...

    def fetch(
        self,
        model: BaseModel,
        query: Query,
        column_fields: typing.Iterable[Field],
        other_fields: typing.Iterable[Field],
    ) -> BaseModel: ...

    def search(
        self,
        model: BaseModel,
        domain: Domain,
        offset: int,
        limit: int | None,
        order: str | None,
        *,
        check_access: bool = True,
        prof: typing.Any = None,
    ) -> Query: ...

    def as_query(self, model: BaseModel, ordered: bool = True) -> Query: ...

    def existing_ids(self, model: BaseModel, ids: typing.Iterable[int]) -> set[int]: ...

    def lock_for_update(
        self, model: BaseModel, *, allow_referencing: bool = False
    ) -> None: ...

    def try_lock_for_update(
        self,
        model: BaseModel,
        *,
        allow_referencing: bool = False,
        limit: int | None = None,
    ) -> BaseModel: ...

    def delete(
        self,
        model: BaseModel,
        sub_ids: tuple[int, ...],
        Data: BaseModel,
        Defaults: BaseModel,
        Attachment: BaseModel,
    ) -> tuple[BaseModel, BaseModel]: ...

    def read_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        ids: typing.Collection[int],
    ) -> list[tuple[int, int]]: ...

    def link_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None: ...

    def unlink_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None: ...


class PostgresBackend:
    supports_parent_store: bool = True

    supports_record_rules: bool = True

    supports_joined_m2m_read: bool = True

    supports_column_scan: bool = True

    supports_translation_terms: bool = True

    __slots__ = ()

    def create_rows(
        self,
        model: BaseModel,
        stored_list: list[dict[str, typing.Any]],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[int]:
        cr = model.env.cr
        ids: list[int] = []
        use_copy = (
            not COPY_DISABLED
            and col_fields
            and len(stored_list) >= COPY_THRESHOLD
            and not cr.in_pipeline
        )
        subprof = _OrmProfile(_orm_crud)

        if use_copy:
            copy_rows = self._prepare_insert_rows(
                model, stored_list, columns, col_fields
            )
            batch_ids = cr.copy_from(
                model._table,
                columns,
                copy_rows,
                returning_ids=True,
                binary=True,
            )
            ids.extend(batch_ids)
            subprof.stop()
            subprof.report(
                _orm_crud,
                "_create %s: %d records via COPY (%d columns)",
                model._name,
                len(stored_list),
                len(columns),
            )
        else:
            if col_fields:
                rows: list[tuple] = self._prepare_insert_rows(
                    model, stored_list, columns, col_fields
                )
            else:
                columns = ["id"]
                rows = [(SQL_DEFAULT,) for _ in stored_list]

            cr.execute(
                SQL(
                    'INSERT INTO %s (%s) VALUES %s RETURNING "id"',
                    SQL.identifier(model._table),
                    SQL(", ").join(map(SQL.identifier, columns)),
                    SQL(", ").join(SQL("(%s)", SQL(", ").join(row)) for row in rows),
                )
            )
            ids.extend(id_ for (id_,) in cr.fetchall())
            subprof.stop()
            subprof.report(
                _orm_crud,
                "_create %s: %d records via INSERT (%d columns)",
                model._name,
                len(stored_list),
                len(columns),
            )
        return ids

    @staticmethod
    def _prepare_insert_rows(
        model: BaseModel,
        stored_list: list[dict[str, typing.Any]],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[tuple]:
        return [
            tuple(
                field.convert_to_column_insert(stored[fname], model, stored)
                if fname in stored
                else None
                for fname, field in zip(columns, col_fields, strict=True)
            )
            for stored in stored_list
        ]

    def update_rows(
        self, model: BaseModel, fnames: tuple[str, ...], rows: list[tuple]
    ) -> None:
        if (values := self._uniform_update_values(rows)) is not None:
            self._update_rows_uniform(model, fnames, [row[0] for row in rows], values)
            return
        for sub_rows in batched(rows, UPDATE_BATCH_SIZE, strict=False):
            self._update_rows_values(model, fnames, sub_rows)

    @staticmethod
    def _uniform_update_values(rows: list[tuple]) -> tuple | None:
        if len(rows) < 2:
            return None
        values = rows[0][1:]
        if not all(isinstance(value, _UNIFORM_UPDATE_TYPES) for value in values):
            return None
        if any(row[1:] != values for row in rows):
            return None
        return values

    @staticmethod
    def _update_assignments(
        model: BaseModel,
        fnames: tuple[str, ...],
        value_sql: Callable[[int, str, SQL, SQL], SQL],
    ) -> tuple[list[SQL], list[SQL]]:
        columns = []
        assignments = []
        for index, fname in enumerate(fnames):
            field = model._fields[fname]
            column_type = field.column_type
            if not field.is_column or column_type is None:
                raise RuntimeError(
                    f"_execute_update: {field} is not a stored column field"
                )
            column = SQL.identifier(fname)
            cast = SQL(column_type[1])  # noqa: E8501  from the field declaration
            expr = value_sql(index, fname, column, cast)
            if field.translate is True:
                expr = SQL(
                    """CASE WHEN %(expr)s IS NULL THEN NULL ELSE
                        COALESCE(%(table)s.%(column)s, jsonb_build_object(
                            'en_US', jsonb_path_query_first(%(expr)s, '$.*')
                        )) || %(expr)s
                    END""",
                    table=SQL.identifier(model._table),
                    column=column,
                    expr=expr,
                )
            if field.company_dependent:
                fallbacks = model.env["ir.default"]._get_field_column_fallbacks(
                    model._name, fname
                )
                expr = SQL(
                    """(SELECT jsonb_object_agg(d.key, d.value)
                    FROM jsonb_each(COALESCE(%(table)s.%(column)s, '{}'::jsonb) || %(expr)s) d
                    JOIN jsonb_each(%(fallbacks)s) f
                    ON d.key = f.key AND d.value != f.value)""",
                    table=SQL.identifier(model._table),
                    column=column,
                    expr=expr,
                    fallbacks=fallbacks,
                )
            columns.append(column)
            assignments.append(SQL("%s = %s", column, expr))
        return columns, assignments

    def _update_rows_values(
        self,
        model: BaseModel,
        fnames: tuple[str, ...],
        rows: tuple[tuple, ...] | list[tuple],
    ) -> None:
        columns, assignments = self._update_assignments(
            model,
            fnames,
            lambda _index, _fname, column, cast: SQL('"__tmp".%s::%s', column, cast),
        )
        model.env.cr.execute(
            SQL(
                """ UPDATE %(table)s
                SET %(assignments)s
                FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                WHERE %(table)s."id" = "__tmp"."id"
            """,
                table=SQL.identifier(model._table),
                assignments=SQL(", ").join(assignments),
                values=SQL(", ").join(rows),
                columns=SQL(", ").join(columns),
            )
        )

    def _update_rows_uniform(
        self, model: BaseModel, fnames: tuple[str, ...], ids: list[int], values: tuple
    ) -> None:
        _columns, assignments = self._update_assignments(
            model,
            fnames,
            lambda index, _fname, _column, cast: SQL("%s::%s", values[index], cast),
        )
        model.env.cr.execute(
            SQL(
                """UPDATE %(table)s SET %(assignments)s WHERE "id" = ANY(%(ids)s)""",
                table=SQL.identifier(model._table),
                assignments=SQL(", ").join(assignments),
                ids=ids,
            )
        )

    def fetch(
        self,
        model: BaseModel,
        query: Query,
        column_fields: typing.Iterable[Field],
        other_fields: typing.Iterable[Field],
    ) -> BaseModel:
        prof = _OrmProfile(_orm_read)
        env = model.env
        context = env.context
        column_fields = OrderedSet(column_fields)
        other_fields = OrderedSet(other_fields)

        if column_fields:
            sql_terms = [SQL.identifier(model._table, "id")]
            for field in column_fields:
                sql = model._field_to_sql(model._table, field.name, query)
                if field.is_binary and (
                    context.get("bin_size") or context.get("bin_size_" + field.name)
                ):
                    sql = SQL("pg_size_pretty(length(%s)::bigint)", sql)
                elif not field.translate:
                    to_flush = (f for f in sql.to_flush if f != field)
                    sql = SQL("%s", sql, to_flush=to_flush)
                sql_terms.append(sql)

            rows = env.execute_query(query.select(*sql_terms))
            prof.mark("sql")

            if not rows:
                return model.browse()

            column_values = zip(*rows, strict=False)
            ids = next(column_values)
            fetched = model.browse(ids)

            for field, values in zip(column_fields, column_values, strict=True):
                if field.is_stored_computed:
                    field._clear_dead_pending(fetched)
                field._insert_cache(fetched, values)
            prof.mark("cache")
        else:
            fetched = model.browse(query)
            prof.mark("sql")
            prof.mark("cache")

        if fetched:
            for field in other_fields:
                field.read(fetched)

        prof.stop("other")
        prof.report(
            _orm_read,
            "_fetch_query %s: %d col + %d other fields -> %d rows",
            model._name,
            len(column_fields),
            len(other_fields),
            len(fetched),
        )

        return fetched

    def search(
        self,
        model: BaseModel,
        domain: Domain,
        offset: int,
        limit: int | None,
        order: str | None,
        *,
        check_access: bool = True,
        prof: typing.Any = None,
    ) -> Query:
        if prof is None:
            prof = _OrmProfile(_orm_read)
        query = Query(model.env, model._table, model._table_sql)
        if not domain.is_true():
            query.add_where(domain._to_sql(model, model._table, query))
        prof.mark("domain")

        if check_access:
            model_sudo = model.sudo().with_context(active_test=False)
            sec_domain = model.env["ir.rule"]._get_domain_accessible_records(
                model._name, "read"
            )
            sec_domain = sec_domain.optimize_full(model_sudo)
            if sec_domain.is_false():
                return self.as_query(model.browse())
            if not sec_domain.is_true():
                query.add_where(sec_domain._to_sql(model_sudo, model._table, query))
        prof.mark("rules")

        if order:
            query.order = model._order_to_sql(order, query) or SQL.identifier(
                model._table, "id"
            )

        if limit is not None and limit is not False:
            query.limit = 1 if limit is True else limit
        if offset is not None and offset is not False:
            query.offset = 1 if offset is True else offset

        prof.stop("query")
        prof.report(_orm_read, "_search %s", model._name)
        return query

    def as_query(self, model: BaseModel, ordered: bool = True) -> Query:
        query = Query(model.env, model._table, model._table_sql)
        query.set_result_ids(model._ids, ordered)
        return query

    def existing_ids(self, model: BaseModel, ids: typing.Iterable[int]) -> set[int]:
        ids = list(ids)
        query = Query(model.env, model._table, model._table_sql)
        query.add_where(SQL("%s = ANY(%s)", SQL.identifier(model._table, "id"), ids))
        return {id_ for [id_] in model.env.execute_query(query.select())}

    @staticmethod
    def _lock_clause(allow_referencing: bool) -> SQL:
        if allow_referencing:
            return SQL("FOR NO KEY UPDATE SKIP LOCKED")
        return SQL("FOR UPDATE SKIP LOCKED")

    def lock_for_update(
        self, model: BaseModel, *, allow_referencing: bool = False
    ) -> None:
        ids = {id_ for id_ in model._ids if id_}
        if not ids:
            return
        query = Query(model.env, model._table, model._table_sql)
        query.add_where(
            SQL("%s = ANY(%s)", SQL.identifier(model._table, "id"), list(ids))
        )
        sql = SQL("%s %s", query.select(), self._lock_clause(allow_referencing))
        rows = model.env.execute_query(sql)
        if len(rows) != len(ids):
            raise LockError(model.env._("Cannot grab a lock on records"))

    def try_lock_for_update(
        self,
        model: BaseModel,
        *,
        allow_referencing: bool = False,
        limit: int | None = None,
    ) -> BaseModel:
        new_ids, ids = partition(lambda i: isinstance(i, NewId), model._ids)
        if limit is not None and len(new_ids) >= limit:
            return model.browse(new_ids[:limit])
        if not ids:
            return model
        if limit is not None:
            query = self.as_query(model.browse(ids), ordered=True)
            query.limit = limit - len(new_ids)
        else:
            query = Query(model.env, model._table, model._table_sql)
            query.add_where(
                SQL("%s = ANY(%s)", SQL.identifier(model._table, "id"), list(ids))
            )
        sql = SQL("%s %s", query.select(), self._lock_clause(allow_referencing))
        real_ids = (id_ for [id_] in model.env.execute_query(sql))
        valid_ids = {*real_ids, *new_ids}
        return model.browse(i for i in model._ids if i in valid_ids)

    def delete(
        self,
        model: BaseModel,
        sub_ids: tuple[int, ...],
        Data: BaseModel,
        Defaults: BaseModel,
        Attachment: BaseModel,
    ) -> tuple[BaseModel, BaseModel]:
        env = model.env
        cr = env.cr
        records = model.browse(sub_ids)

        cr.execute(
            SQL(
                "DELETE FROM %s WHERE id = ANY(%s)",
                SQL.identifier(model._table),
                list(sub_ids),
            )
        )

        data = Data.search([("model", "=", model._name), ("res_id", "in", sub_ids)])

        cr.execute(
            SQL(
                "SELECT id FROM ir_attachment WHERE res_model=%s AND res_id = ANY(%s)",
                model._name,
                list(sub_ids),
            )
        )
        attachments = Attachment.browse(row[0] for row in cr.fetchall())

        many2one_fields = env.registry.many2one_company_dependents[model._name]
        uninstalling = env.context.get(MODULE_UNINSTALL_FLAG)
        if many2one_fields and not uninstalling:
            self._unlink_default_guard(model, sub_ids, Defaults, many2one_fields)

        if many2one_fields and not all(
            isinstance(id_, int) and id_ > 0 for id_ in sub_ids
        ):
            raise TypeError(
                f"_unlink_process_batch: sub_ids must be positive ints, got {sub_ids!r}"
            )
        for field in many2one_fields:
            referrer = env[field.model_name]
            if field.ondelete == "restrict" and not uninstalling:
                self._unlink_restrict_guard(model, referrer, field, sub_ids)
            else:
                self._unlink_clear_company_dependent(referrer, field, sub_ids)

        Defaults.discard_records(records)

        return data, attachments

    @staticmethod
    def _unlink_default_guard(
        model: BaseModel,
        sub_ids: tuple[int, ...],
        Defaults: BaseModel,
        many2one_fields,
    ) -> None:
        IrModelFields = model.env["ir.model.fields"]
        field_ids = tuple(
            IrModelFields._get_ids_by_name(field.model_name).get(field.name)
            for field in many2one_fields
        )
        sub_ids_json_text = tuple(json_dumps(id_) for id_ in sub_ids)
        if default := Defaults.search(
            [
                ("field_id", "in", field_ids),
                ("json_value", "in", sub_ids_json_text),
            ],
            limit=1,
            order="id desc",
        ):
            ir_field = default.field_id.sudo()
            field = model.env[ir_field.model]._fields[ir_field.name]
            record = model.browse(json_loads(default.json_value))
            raise UserError(
                _(
                    "Unable to delete %(record)s because it is used as the default value of %(field)s",
                    record=record,
                    field=field,
                )
            )

    @staticmethod
    def _unlink_restrict_guard(
        model: BaseModel, referrer: BaseModel, field: Field, sub_ids: tuple[int, ...]
    ) -> None:
        if res := model.env.execute_query(
            SQL(
                """
            SELECT id, %(field)s
            FROM %(table)s
            WHERE %(field)s IS NOT NULL
            AND %(field)s @? %(jsonpath)s
            ORDER BY id
            LIMIT 1
            """,
                table=SQL.identifier(referrer._table),
                field=SQL.identifier(field.name),
                jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
            )
        ):
            on_restrict_id, field_json = res[0]
            to_delete_id = next(iter(field_json.values()))
            on_restrict_record = referrer.browse(on_restrict_id)
            to_delete_record = model.browse(to_delete_id)
            raise UserError(
                _(
                    "You cannot delete %(to_delete_record)s, as it is used by %(on_restrict_record)s",
                    to_delete_record=to_delete_record,
                    on_restrict_record=on_restrict_record,
                )
            )

    @staticmethod
    def _unlink_clear_company_dependent(
        referrer: BaseModel, field: Field, sub_ids: tuple[int, ...]
    ) -> None:
        affected = referrer.env.execute_query(
            SQL(
                """
            UPDATE %(table)s
            SET %(field)s = (
                SELECT jsonb_object_agg(
                    key,
                    CASE
                        WHEN value::int4 in %(ids)s THEN NULL
                        ELSE value::int4
                    END)
                FROM jsonb_each_text(%(field)s)
            )
            WHERE %(field)s IS NOT NULL
            AND %(field)s @? %(jsonpath)s
            RETURNING id
            """,
                table=SQL.identifier(referrer._table),
                field=SQL.identifier(field.name),
                ids=sub_ids,
                jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
            )
        )
        if affected:
            affected_recs = referrer.browse(row[0] for row in affected)
            affected_recs.modified([field.name])

    def read_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        ids: typing.Collection[int],
    ) -> list[tuple[int, int]]:
        sql_id1 = SQL.identifier(relation, column1)
        sql_id2 = SQL.identifier(relation, column2)
        rows = model.env.execute_query(
            SQL(
                "SELECT %s, %s FROM %s WHERE %s = ANY(%s)",
                sql_id1,
                sql_id2,
                SQL.identifier(relation),
                sql_id1,
                list(ids),
            )
        )
        return [(id1, id2) for id1, id2 in rows]

    def link_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        model.env.cr.execute(
            SQL(
                "INSERT INTO %s (%s, %s) VALUES %s ON CONFLICT DO NOTHING",
                SQL.identifier(relation),
                SQL.identifier(column1),
                SQL.identifier(column2),
                SQL(", ").join(pairs),
            )
        )

    def unlink_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        xs_to_ys: dict[frozenset, set] = defaultdict(set)
        y_to_xs: dict[typing.Any, set] = defaultdict(set)
        for x, y in pairs:
            y_to_xs[y].add(x)
        for y, xs in y_to_xs.items():
            xs_to_ys[frozenset(xs)].add(y)
        model.env.cr.execute(
            SQL(
                "DELETE FROM %s WHERE %s",
                SQL.identifier(relation),
                SQL(" OR ").join(
                    SQL(
                        "%s = ANY(%s) AND %s = ANY(%s)",
                        SQL.identifier(column1),
                        list(xs),
                        SQL.identifier(column2),
                        list(ys),
                    )
                    for xs, ys in xs_to_ys.items()
                ),
            )
        )


POSTGRES_BACKEND = PostgresBackend()


class InMemoryBackend:
    supports_parent_store: bool = False

    supports_record_rules: bool = False

    supports_joined_m2m_read: bool = False

    supports_column_scan: bool = False

    supports_translation_terms: bool = False

    __slots__ = ("storage",)

    def __init__(self, storage: DictBackend):
        self.storage = storage

    def create_rows(
        self,
        model: BaseModel,
        stored_list: list[dict[str, typing.Any]],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[int]:
        row_dicts: list[dict[str, typing.Any]] = []
        new_ids: list[int] = []
        for stored in stored_list:
            new_id = self.storage.next_id(model._table)
            row_dict: dict[str, typing.Any] = {"id": new_id}
            for fname, field in zip(columns, col_fields, strict=True):
                if fname in stored:
                    row_dict[fname] = _unwrap_json(
                        field.convert_to_column_insert(stored[fname], model, stored)
                    )
            row_dicts.append(row_dict)
            new_ids.append(new_id)
        self.storage.put_rows(model._table, row_dicts)
        return new_ids

    def update_rows(
        self, model: BaseModel, fnames: tuple[str, ...], rows: list[tuple]
    ) -> None:
        fields_map = model._fields
        updates = []
        for row in rows:
            id_ = row[0]
            values: dict[str, typing.Any] = {}
            for fname, value in zip(fnames, row[1:], strict=True):
                value = _unwrap_json(value)
                field = fields_map.get(fname)
                if (
                    value is not None
                    and field is not None
                    and (field.translate is True or field.company_dependent)
                    and isinstance(value, dict)
                ):
                    old_row = self.storage.get_row(model._table, id_)
                    old = old_row.get(fname) if old_row else None
                    if field.translate is True and not isinstance(old, dict):
                        old = {"en_US": next(iter(value.values()))}
                    if isinstance(old, dict):
                        value = {**old, **value}
                values[fname] = value
            updates.append((id_, values))
        self.storage.upsert_rows(model._table, updates)

    def fetch(
        self,
        model: BaseModel,
        query: Query,
        column_fields: typing.Iterable[Field],
        other_fields: typing.Iterable[Field],
    ) -> BaseModel:
        result_ids = query._ids
        if result_ids is None:
            result_ids = tuple(self.storage.table_ids(model._table))

        if not result_ids:
            return model.browse()

        fetched = model.browse(result_ids)
        column_fields = list(column_fields)
        if column_fields:
            env = model.env
            _fdc = env._field_depends_context
            field_caches: dict = {}
            for field in column_fields:
                if field not in _fdc:
                    field_caches[field] = env._core.get_field_data(field)
                else:
                    try:
                        field_caches[field] = field._get_cache(env)
                    except (KeyError, AttributeError, TypeError) as e:
                        _logger.debug(
                            "DictBackend cache load skipped %s.%s: %s",
                            model._name,
                            field.name,
                            e,
                        )
                        field_caches[field] = env._core.get_field_data(field)
            for record_id in result_ids:
                row = self.storage.get_row(model._table, record_id)
                if row is not None:
                    for field in column_fields:
                        value = _column_read_value(field, row.get(field.name), env)
                        fc = field_caches[field]
                        fc.setdefault(
                            record_id,
                            field.convert_to_cache(value, fetched),
                        )

        if fetched:
            for field in other_fields:
                field.read(fetched)
        return fetched

    def search(
        self,
        model: BaseModel,
        domain: Domain,
        offset: int,
        limit: int | None,
        order: str | None,
        *,
        check_access: bool = True,
        prof: typing.Any = None,
    ) -> Query:
        model.env.flush_all()

        all_ids = self.storage.table_ids(model._table)
        if not all_ids:
            return model.browse()._as_query(ordered=False)

        all_records = model.browse(all_ids)
        rows = self.storage.get_rows(model._table, all_ids)

        env = model.env
        fields_meta = model._fields
        _fdc = env._field_depends_context
        storable: list[tuple] = []
        sentinel = model.browse(all_ids[0])
        for fname, field in fields_meta.items():
            if fname != "id" and field.store and field.column_type:
                if field not in _fdc:
                    storable.append((fname, field, env._core.get_field_data(field)))
                else:
                    try:
                        storable.append((fname, field, field._get_cache(env)))
                    except (KeyError, AttributeError, TypeError) as e:
                        _logger.debug(
                            "DictBackend cache load skipped %s.%s: %s",
                            model._name,
                            fname,
                            e,
                        )

        for fname, field, field_cache in storable:
            convert = field.convert_to_cache
            for record_id in all_ids:
                row = rows.get(record_id)
                if row is not None and fname in row:
                    value = _column_read_value(field, row[fname], env)
                    field_cache[record_id] = convert(value, sentinel)

        if not domain.is_true():
            matching = all_records.filtered_domain(domain)
        else:
            matching = all_records

        if order:
            matching = matching.sorted(key=order)

        ids = matching._ids
        if offset:
            ids = ids[offset:]
        if limit is not None and limit is not False:
            ids = ids[:limit]

        query = Query(model.env, model._table, model._table_sql)
        query._ids = tuple(ids)
        return query

    def as_query(self, model: BaseModel, ordered: bool = True) -> Query:
        query = Query(model.env, model._table, model._table_sql)
        query._ids = tuple(model._ids)
        return query

    def existing_ids(self, model: BaseModel, ids: typing.Iterable[int]) -> set[int]:
        return set(self.storage.contains_ids(model._table, list(ids)))

    def lock_for_update(
        self, model: BaseModel, *, allow_referencing: bool = False
    ) -> None:
        ids = {id_ for id_ in model._ids if id_}
        if not ids:
            return
        if len(self.storage.contains_ids(model._table, list(ids))) != len(ids):
            raise LockError(model.env._("Cannot grab a lock on records"))

    def try_lock_for_update(
        self,
        model: BaseModel,
        *,
        allow_referencing: bool = False,
        limit: int | None = None,
    ) -> BaseModel:
        new_ids, real = partition(lambda i: isinstance(i, NewId), model._ids)
        lockable = self.storage.contains_ids(model._table, real) | set(new_ids)
        locked = [i for i in model._ids if i in lockable]
        if limit is not None:
            locked = locked[:limit]
        return model.browse(locked)

    def delete(
        self,
        model: BaseModel,
        sub_ids: tuple[int, ...],
        Data: BaseModel,
        Defaults: BaseModel,
        Attachment: BaseModel,
    ) -> tuple[BaseModel, BaseModel]:
        self.storage.remove_rows(model._table, list(sub_ids))
        return Data.browse(), Attachment.browse()

    def _m2m_rows(self, relation: str):
        for row_id in self.storage.table_ids(relation):
            row = self.storage.get_row(relation, row_id)
            if row is not None:
                yield row_id, row

    def read_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        ids: typing.Collection[int],
    ) -> list[tuple[int, int]]:
        wanted = set(ids)
        return [
            (row[column1], row[column2])
            for _row_id, row in self._m2m_rows(relation)
            if row.get(column1) in wanted
        ]

    def link_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        existing: set[tuple] = {
            (row.get(column1), row.get(column2))
            for _row_id, row in self._m2m_rows(relation)
        }
        to_insert = []
        for pair in pairs:
            key = tuple(pair)
            if key not in existing:
                existing.add(key)
                to_insert.append(key)
        if to_insert:
            self.storage.insert_rows(relation, [column1, column2], to_insert)

    def unlink_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        doomed = {tuple(pair) for pair in pairs}
        row_ids = [
            row_id
            for row_id, row in self._m2m_rows(relation)
            if (row.get(column1), row.get(column2)) in doomed
        ]
        if row_ids:
            self.storage.remove_rows(relation, row_ids)
