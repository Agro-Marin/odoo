import typing
from datetime import date, datetime

from psycopg.types.json import Json as PsycopgJson

from odoo.db import schema as sql
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.misc import PENDING, SENTINEL

if typing.TYPE_CHECKING:
    from .._typing import BaseModel, ModelLike

    M = typing.TypeVar("M", bound=BaseModel)
    T = typing.TypeVar("T")


from ._field_stubs import _FieldStubs


class _FieldConvertMixin(_FieldStubs):
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        if value is None or value is False:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            return value.decode()
        if isinstance(value, (int, float)):
            return str(value)
        raise TypeError(f"Invalid column value for {self}: {value!r}")

    @staticmethod
    def _to_json_value(value: typing.Any) -> typing.Any:
        if isinstance(value, datetime):
            return value.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        if isinstance(value, date):
            return value.strftime(DEFAULT_SERVER_DATE_FORMAT)
        return value

    def convert_to_column_insert(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        value = self.convert_to_column(value, record, values, validate)
        if self.translate:
            if value is None:
                return None
            return PsycopgJson({"en_US": value, record.env.lang or "en_US": value})
        if not self.company_dependent:
            return value
        fallback = self._company_dependent_fallback_raw(record)
        if value == self.convert_to_column(fallback, record):
            return None
        return PsycopgJson({record.env.company.id: self._to_json_value(value)})

    def get_column_update(self, record: ModelLike) -> typing.Any:
        record_id = record.id
        field_cache = record.env._core.get_field_data(self)
        if self.translate is True:
            langs_dict = {}
            flat_value = SENTINEL
            found = False
            for cache_key, sub_cache in field_cache.items():
                if not isinstance(sub_cache, dict):
                    if cache_key == record_id:
                        found = True
                        if sub_cache is not None:
                            flat_value = sub_cache
                    continue
                if (value := sub_cache.get(record_id, SENTINEL)) is not SENTINEL:
                    found = True
                    lang = cache_key[0]
                    if value is not None:
                        langs_dict[lang] = value
            if not found:
                raise KeyError(record_id)
            if not langs_dict and flat_value is not SENTINEL:
                langs_dict[record.env.lang or "en_US"] = flat_value
            return PsycopgJson(langs_dict) if langs_dict else None
        if self.translate:
            value = field_cache[record_id]
            return PsycopgJson(value) if value else None
        if not self.company_dependent:
            if not self._is_context_dependent(record.env):
                value = field_cache[record_id]
                if value is PENDING:
                    return PENDING
                return self.convert_to_column(value, record, validate=False)
            found = False
            for cache in field_cache.values():
                if (value := cache.get(record_id, SENTINEL)) is not SENTINEL:
                    found = True
                    if value is not PENDING:
                        return self.convert_to_column(value, record, validate=False)
            if found:
                return PENDING
            raise KeyError(record_id)
        values = {}
        flat_value = SENTINEL
        found = False
        saw_pending = False
        for ctx_key, cache in field_cache.items():
            if not isinstance(cache, dict):
                if ctx_key == record_id:
                    found = True
                    if cache is not None:
                        flat_value = cache
                continue
            if (value := cache.get(record_id, SENTINEL)) is not SENTINEL:
                found = True
                if value is PENDING:
                    saw_pending = True
                else:
                    values[ctx_key[0]] = self._to_json_value(
                        self.convert_to_column(value, record)
                    )
        if not found:
            raise KeyError(record_id)
        if not values and flat_value is not SENTINEL:
            values[record.env.company.id] = self._to_json_value(
                self.convert_to_column(flat_value, record)
            )
        if not values and saw_pending:
            return PENDING
        return PsycopgJson(values) if values else None

    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> typing.Any:
        return value

    def convert_to_record(self, value: typing.Any, record: ModelLike) -> T:
        return False if value is None else value

    def convert_to_read(
        self, value: typing.Any, record: ModelLike, use_display_name: bool = True
    ) -> typing.Any:
        return False if value is None else value

    def convert_to_write(self, value: typing.Any, record: ModelLike) -> typing.Any:
        cache_value = self.convert_to_cache(value, record, validate=False)
        record_value = self.convert_to_record(cache_value, record)
        return self.convert_to_read(record_value, record)

    def convert_to_export(self, value: typing.Any, record: ModelLike) -> typing.Any:
        if not value:
            return ""
        return value

    def convert_to_display_name(
        self, value: typing.Any, record: ModelLike
    ) -> str | typing.Literal[False]:
        return str(value) if value else False

    @property
    def column_order(self) -> int:
        return (
            0
            if self.column_type is None
            else sql.SQL_ORDER_BY_TYPE[self.column_type[0]]
        )
