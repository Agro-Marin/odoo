"""The convert_to_* value-conversion pipeline (cache/record/write/column/...).

Extracted from the Field god-class; mixed into Field (base.py).
"""

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
    """The convert_to_* value-conversion pipeline (cache/record/write/column/...)."""

    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        """Convert ``value`` from the write format to a SQL parameter for
        UPDATE conditions and column comparisons.

        Base scalar conversion. For INSERT use :meth:`convert_to_column_insert`
        (adds translated/company-dependent JSONB wrapping); to flush dirty cache,
        :meth:`get_column_update` reads from cache and delegates here.
        """
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
        """Convert a column value to a JSON-safe type for JSONB storage."""
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
        """Convert ``value`` from the write format to a SQL parameter for
        INSERT/COPY queries.  Delegates to :meth:`convert_to_column` for the
        scalar conversion, then wraps in JSONB for translated or
        company-dependent fields.

        Used by :meth:`~odoo.orm.models.mixins.create.CreateMixin._create`.
        """
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
        """Read ``record``'s dirty cache value as a SQL parameter for UPDATE.

        The cache → SQL path used by
        :meth:`~odoo.orm.models.mixins.recompute.RecomputeMixin._flush`. Most fields
        delegate to :meth:`convert_to_column`; translated and company-dependent
        fields assemble JSONB directly.
        """
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
            # A context-dependent field has one column but one cache per
            # context, and only the contexts a compute has run in hold a value.
            # Returning the first hit let a PENDING slot outrank a real value
            # written in another context: ``_flush`` has already popped the
            # dirty flag by then, so it dropped the column and the write was
            # lost with no error.  A real value is authoritative wherever it
            # comes from; PENDING only means "not computed *here*".
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
            # Every company slot is still uncomputed: report that rather than
            # returning ``None``, which would flush SQL NULL over the column.
            return PENDING
        return PsycopgJson(values) if values else None

    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> typing.Any:
        """Convert ``value`` to the cache format. Entry point of the WRITE path:
        values from :meth:`BaseModel.write`, :meth:`BaseModel.create`, or direct
        assignment pass through here before being stored in the field cache.

        If the value represents a recordset, it should be added for
        prefetching on ``record``.

        :param value: a value in write format (from user/API)
        :param record: target recordset (used for env, validation context)
        :param bool validate: when True, field-specific validation of
            ``value`` will be performed
        """
        return value

    def convert_to_record(self, value: typing.Any, record: ModelLike) -> T:
        """Convert ``value`` from the cache format to the record format — the
        Python value returned by ``record.field``.  This is the READ path
        exit point, called by :meth:`__get__`.

        If the value represents a recordset, it should share the prefetching
        of ``record``.
        """
        return False if value is None else value

    def convert_to_read(
        self, value: typing.Any, record: ModelLike, use_display_name: bool = True
    ) -> typing.Any:
        """Convert ``value`` from the record format to the EXPORT format
        returned by :meth:`BaseModel.read` and consumed by the web client.
        For relational fields this adds ``display_name``; for others it is
        typically an identity.

        :param value: a value in record format (from :meth:`convert_to_record`)
        :param record: source recordset
        :param bool use_display_name: when True, the value's display name will
            be computed using ``display_name``, if relevant for the field
        """
        return False if value is None else value

    def convert_to_write(self, value: typing.Any, record: ModelLike) -> typing.Any:
        """Convert ``value`` from any format to the write format accepted by
        :meth:`BaseModel.write`.  Used by :meth:`__set__` on real records to
        roundtrip a value through the conversion pipeline before delegating
        to ``records.write()``.

        Default implementation chains: cache → record → read.
        """
        cache_value = self.convert_to_cache(value, record, validate=False)
        record_value = self.convert_to_record(cache_value, record)
        return self.convert_to_read(record_value, record)

    def convert_to_export(self, value: typing.Any, record: ModelLike) -> typing.Any:
        """Convert ``value`` from the record format to the export format."""
        if not value:
            return ""
        return value

    def convert_to_display_name(
        self, value: typing.Any, record: ModelLike
    ) -> str | typing.Literal[False]:
        """Convert ``value`` from the record format to a suitable display name."""
        return str(value) if value else False

    @property
    def column_order(self) -> int:
        """Prescribed column order in table."""
        return (
            0
            if self.column_type is None
            else sql.SQL_ORDER_BY_TYPE[self.column_type[0]]
        )
