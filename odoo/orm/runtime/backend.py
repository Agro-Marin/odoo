from __future__ import annotations

import logging
import typing

from psycopg.types.json import Json, Jsonb

from odoo.exceptions import LockError
from odoo.tools import Query, partition

from ..primitives import NewId

if typing.TYPE_CHECKING:
    from ..components.storage import DictBackend
    from ..domain import Domain
    from ..fields import Field
    from ..models.base import BaseModel

_logger = logging.getLogger("odoo.orm.backend")


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
        sub_ids: typing.Iterable[int],
        Data: BaseModel,
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


class InMemoryBackend:
    supports_parent_store: bool = False

    supports_record_rules: bool = False

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
        return set(self.storage.contains_ids(model._table, ids))

    def lock_for_update(
        self, model: BaseModel, *, allow_referencing: bool = False
    ) -> None:
        ids = {id_ for id_ in model._ids if id_}
        if not ids:
            return
        if len(self.storage.contains_ids(model._table, ids)) != len(ids):
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
        sub_ids: typing.Iterable[int],
        Data: BaseModel,
        Attachment: BaseModel,
    ) -> tuple[BaseModel, BaseModel]:
        self.storage.delete_rows(model._table, list(sub_ids))
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
        existing = {
            (row.get(column1), row.get(column2))
            for _row_id, row in self._m2m_rows(relation)
        }
        to_insert = []
        for pair in pairs:
            pair = tuple(pair)
            if pair not in existing:
                existing.add(pair)
                to_insert.append(pair)
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
            self.storage.delete_rows(relation, row_ids)
