"""The convert_to_* value-conversion pipeline (cache/record/write/column/...).

Extracted from the Field god-class; mixed into Field (base.py).
"""

import typing
from datetime import date, datetime

from psycopg.types.json import Json as PsycopgJson

from odoo.tools import (
    DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_DATETIME_FORMAT,
    sql,
)
from odoo.tools.misc import PENDING, SENTINEL

if typing.TYPE_CHECKING:
    from .._typing import BaseModel

    M = typing.TypeVar("M", bound=BaseModel)
    # Field's value type parameter (Field[T]); used in convert_to_record's return
    # annotation. Lazy (PEP 649), so only needed for type-checking.
    T = typing.TypeVar("T")


from ._field_stubs import _FieldStubs


class _FieldConvertMixin(_FieldStubs):
    """The convert_to_* value-conversion pipeline (cache/record/write/column/...)."""

    def convert_to_column(
        self,
        value: typing.Any,
        record: BaseModel,
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
        elif isinstance(value, bytes):
            return value.decode()
        else:
            return str(value)

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
        record: BaseModel,
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
        # superuser fallback (shared helper): the dedup must compare against
        # the same fallback the read paths COALESCE to, or a user-scoped
        # ir.default makes the inserted value read back as the global default
        fallback = self._company_dependent_fallback_raw(record)
        if value == self.convert_to_column(fallback, record):
            return None
        return PsycopgJson({record.env.company.id: self._to_json_value(value)})

    def get_column_update(self, record: BaseModel) -> typing.Any:
        """Read ``record``'s dirty cache value as a SQL parameter for UPDATE.

        The cache → SQL path used by
        :meth:`~odoo.orm.models.mixins.recompute.RecomputeMixin._flush`. Most fields
        delegate to :meth:`convert_to_column`; translated and company-dependent
        fields assemble JSONB directly.
        """
        record_id = record.id
        field_cache = record.env._core.get_field_data(self)
        if self.translate is True:
            # Model translation: reconstruct {lang: value} from per-lang sub-dicts
            # (mirrors the company_dependent pattern below).
            langs_dict = {}
            flat_value = SENTINEL
            for cache_key, sub_cache in field_cache.items():
                if not isinstance(sub_cache, dict):
                    # Stale flat entry ({id: scalar}) written before
                    # field_depends_context was populated (e.g. a
                    # _load_module_terms flush). Keep it as a fallback: a value
                    # surviving ONLY in a flat entry must not flush as SQL NULL
                    # (NotNullViolation on required translatable fields).
                    if cache_key == record_id and sub_cache is not None:
                        flat_value = sub_cache
                    continue
                if (value := sub_cache.get(record_id, SENTINEL)) is not SENTINEL:
                    lang = cache_key[0]
                    if value is not None:
                        langs_dict[lang] = value
            if not langs_dict and flat_value is not SENTINEL:
                # Only a stale flat entry held a value: preserve it under the
                # current language rather than overwriting the column with NULL.
                langs_dict[record.env.lang or "en_US"] = flat_value
            return PsycopgJson(langs_dict) if langs_dict else None
        if self.translate:
            # callable translate: single flat dict {id: {lang: value}}
            value = field_cache[record_id]
            return PsycopgJson(value) if value else None
        if not self.company_dependent:
            if not self._is_context_dependent(record.env):
                # Fast path: direct cache read + column conversion (most fields)
                value = field_cache[record_id]
                if value is PENDING:
                    return PENDING
                return self.convert_to_column(value, record, validate=False)
            # Context-dependent: find first available value across contexts
            for cache in field_cache.values():
                if (value := cache.get(record_id, SENTINEL)) is not SENTINEL:
                    if value is PENDING:
                        return PENDING
                    return self.convert_to_column(value, record, validate=False)
            raise AssertionError(
                f"Value not in cache for field {self} and id={record_id}"
            )
        # Company-dependent: collect values from all company contexts into JSONB
        values = {}
        flat_value = SENTINEL
        for ctx_key, cache in field_cache.items():
            if not isinstance(cache, dict):
                # Stale flat entry (see the translate-is-True branch above):
                # keep a non-None one as a fallback so a value surviving only in
                # a flat entry is not flushed as NULL. The is-not-None guard also
                # avoids 'NoneType has no attribute get'.
                if ctx_key == record_id and cache is not None:
                    flat_value = cache
                continue
            if (
                value := cache.get(record_id, SENTINEL)
            ) is not SENTINEL and value is not PENDING:
                values[ctx_key[0]] = self._to_json_value(
                    self.convert_to_column(value, record)
                )
        if not values and flat_value is not SENTINEL:
            # Only a stale flat entry held a value: preserve it under the current
            # company rather than overwriting the column with NULL.
            values[record.env.company.id] = self._to_json_value(
                self.convert_to_column(flat_value, record)
            )
        return PsycopgJson(values) if values else None

    def convert_to_cache(
        self, value: typing.Any, record: BaseModel, validate: bool = True
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

    def convert_to_record(self, value: typing.Any, record: BaseModel) -> T:
        """Convert ``value`` from the cache format to the record format — the
        Python value returned by ``record.field``.  This is the READ path
        exit point, called by :meth:`__get__`.

        If the value represents a recordset, it should share the prefetching
        of ``record``.
        """
        return False if value is None else value

    def convert_to_read(
        self, value: typing.Any, record: BaseModel, use_display_name: bool = True
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

    def convert_to_write(self, value: typing.Any, record: BaseModel) -> typing.Any:
        """Convert ``value`` from any format to the write format accepted by
        :meth:`BaseModel.write`.  Used by :meth:`__set__` on real records to
        roundtrip a value through the conversion pipeline before delegating
        to ``records.write()``.

        Default implementation chains: cache → record → read.
        """
        cache_value = self.convert_to_cache(value, record, validate=False)
        record_value = self.convert_to_record(cache_value, record)
        return self.convert_to_read(record_value, record)

    def convert_to_export(self, value: typing.Any, record: BaseModel) -> typing.Any:
        """Convert ``value`` from the record format to the export format."""
        if not value:
            return ""
        return value

    def convert_to_display_name(
        self, value: typing.Any, record: BaseModel
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
