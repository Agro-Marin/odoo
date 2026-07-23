"""Read operations mixin for BaseModel."""

import logging
import typing
from collections import defaultdict, deque
from typing import Self

from odoo_rust import (
    batch_cache_fill as _batch_cache_fill_rust,  # type: ignore[import-untyped]
)

from odoo.exceptions import MissingError
from odoo.tools import SQL, OrderedSet
from odoo.tools.misc import PENDING, SENTINEL
from odoo.tools.orm_profiler import _OrmProfile

from ... import decorators as api
from ..._typing import ValuesType
from ...primitives import LOG_ACCESS_COLUMNS
from ._cache_scan import can_scan_read
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from ...fields.base import Field
    from ...tools import Query

_logger = logging.getLogger("odoo.models")
_orm_read = logging.getLogger("odoo.orm.read")


class ReadMixin(_ModelStubs):
    """Mixin providing read and fetch operations for recordsets."""

    __slots__ = ()

    @api.model
    def fields_get(
        self,
        allfields: Collection[str] | None = None,
        attributes: Collection[str] | None = None,
    ) -> dict[str, ValuesType]:
        """Return the definition of each field.

        The returned value is a dictionary (indexed by field name) of
        dictionaries. The _inherits'd fields are included. The string, help,
        and selection (if present) attributes are translated.

        :param allfields: fields to document, all if empty or not provided
        :param attributes: attributes to return for each field, all if empty or not provided
        :return: dictionary mapping field names to a dictionary mapping attributes to values.
        """
        res = {}
        for fname, field in self._fields.items():
            if allfields and fname not in allfields:
                continue
            if not self._has_field_access(field, "read"):
                continue

            description = field.get_description(self.env, attributes=attributes)
            if "readonly" in description:
                description["readonly"] = description[
                    "readonly"
                ] or not self._has_field_access(field, "write")
            res[fname] = description

        return res

    @api.readonly
    def read(
        self, fields: Sequence[str] | None = None, load: str = "_classic_read"
    ) -> list[ValuesType]:
        """Read the requested fields for the records in ``self``, and return their
        values as a list of dicts.

        :param fields: field names to return (default is all fields)
        :param load: loading mode, currently the only option is to set to
            ``None`` to avoid loading the `display_name` of m2o fields
        :return: a list of dictionaries mapping field names to their values,
                 with one dictionary per record
        :raise AccessError: if user is not allowed to access requested information

        Unknown or non-string field names (e.g. integer field ids sent by the
        web client) are not fatal here: they are logged as a warning and
        dropped from the result, so a typo'd name simply yields a dict without
        that key. (``search``/``create``/``write`` still raise ``ValueError``
        for unknown fields; only ``read`` is lenient.)

        This is a high-level method that is not supposed to be overridden. To
        modify how fields are read from the database, see methods
        :meth:`_fetch_query` and :meth:`_read_format`.
        """
        prof = _OrmProfile(_orm_read)

        if not fields:
            fields = list(self.fields_get(attributes=()))
        else:
            # Sanitize field names: the web client may send non-string values
            # (e.g. integer field IDs) which are invalid for the ORM.
            _model_fields = self._fields
            bad = [
                f for f in fields if not isinstance(f, str) or f not in _model_fields
            ]
            if bad:
                _logger.warning("Invalid field(s) %r on %r, skipping", bad, self._name)
                fields = [
                    f for f in fields if isinstance(f, str) and f in _model_fields
                ]
            if not self and not self.env.su:
                # check field access, otherwise done during fetch()
                self._determine_fields_to_fetch(fields)
        self._origin.fetch(fields)
        prof.mark("fetch")
        result = self._read_format(fnames=fields, load=load)

        prof.stop()
        if prof.debug:
            _orm_read.debug(
                "[%.3f ms] read %s: %d records, %d fields | fetch=%.1f format=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(self),
                len(fields),
                prof.ms("start", "fetch"),
                prof.ms("fetch", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_read(self._name, len(self), prof.elapsed)

        return result

    def _read_format(
        self, fnames: Sequence[str], load: str = "_classic_read"
    ) -> list[ValuesType]:
        """Return a list of dicts (one per existing record) mapping field names to
        values, in the format expected by :meth:`read`.  Unlike ``read`` this
        reads from cache, avoiding a query when possible.

        Properties fields use ``convert_to_read_multi`` to batch record
        existence, display names, etc.
        """
        use_display_name = load == "_classic_read"
        env = self.env
        ids = self._ids
        _fields = self._fields
        _SENTINEL = SENTINEL
        _PENDING = PENDING

        # Classify fields: scalar stored fields that can use the fast path
        # (inline dict.get + identity conversion) vs everything else that
        # needs singleton records for convert_to_record / __get__.
        scalar_fnames = []
        record_fnames = []
        for name in fnames:
            field = _fields[name]
            # Enforce field-group ACL here, before any value is read from the
            # cache.  The fast paths below bypass ``Field.__get__`` (which
            # normally gates access), so without this a group-restricted field
            # leaks whenever its value is cache-warm — including on all-NewId
            # recordsets, where ``fetch()`` returns early and never checks.
            field.ensure_access(self)
            if can_scan_read(field):
                scalar_fnames.append(name)
            else:
                record_fnames.append(name)

        # Phase 1: scalar stored fields — inline cache dict.get, skip
        # read_cache/convert_to_record/convert_to_read (chain reduces to
        # ``none_val if value is None else cache_value``).
        results = [{"id": id_} for id_ in ids]
        for name in scalar_fnames:
            field = _fields[name]
            field.ensure_computed(self)
            field_cache = field._get_cache(env)
            # None replacement: False / 0 / 0.0 depending on type.
            none_val = field.convert_to_record(None, None)
            if type(field_cache) is dict:
                # Rust path: fill cached values in one C-level pass, return only
                # miss indices.  Needs a plain dict (not a translated LangProxy).
                miss_indices = _batch_cache_fill_rust(
                    field_cache, ids, results, name, _PENDING, none_val
                )
                for idx in miss_indices:
                    vals = results[idx]
                    if not vals:
                        continue
                    try:
                        record = self.browse((ids[idx],))
                        vals[name] = field.convert_to_read(
                            record[name], record, use_display_name
                        )
                    except MissingError:
                        vals.clear()
            else:
                for id_, vals in zip(ids, results, strict=True):
                    if not vals:
                        continue
                    cache_value = field_cache.get(id_, _SENTINEL)
                    if cache_value is _SENTINEL or cache_value is _PENDING:
                        # Cache miss after fetch(): record missing or a NewId.
                        # Fall back to __get__ via singleton.  Wrap in a tuple —
                        # NewId.__bool__ is False, so bare browse() would be empty.
                        try:
                            record = self.browse((id_,))
                            vals[name] = field.convert_to_read(
                                record[name], record, use_display_name
                            )
                        except MissingError:
                            vals.clear()
                    elif cache_value is None:
                        vals[name] = none_val
                    else:
                        vals[name] = cache_value

        if not record_fnames:
            return [vals for vals in results if vals]

        # Phase 2: fields needing singleton records (relational, translate,
        # html, binary, json, properties, non-stored computed).
        # strict=True: results has one entry per record, so any length
        # mismatch indicates an upstream bug in fetch().
        data = list(zip(self, results, strict=True))

        for name in record_fnames:
            field = _fields[name]
            if field.type == "properties":
                values_list = []
                records = []
                valid_data = []
                for record, vals in data:
                    # Skip records cleared by an earlier field's MissingError,
                    # else a successful properties read would repopulate the
                    # empty dict and leak a partial record through the filter.
                    if not vals:
                        continue
                    try:
                        values_list.append(record[name])
                        records.append(record.id)
                        valid_data.append((record, vals))
                    except MissingError:
                        vals.clear()

                prop_results = field.convert_to_read_multi(
                    values_list, self.browse(records)
                )
                for (_, vals), convert_result in zip(
                    valid_data, prop_results, strict=True
                ):
                    vals[name] = convert_result
                continue

            if field.store:
                # Stored field: bypass __get__, use ensure_computed/read_cache.
                field.ensure_computed(self)
                _read_cache = field.read_cache
                convert_to_record = field.convert_to_record
                convert_to_read = field.convert_to_read
                for record, vals in data:
                    if not vals:
                        continue
                    hit, cache_value = _read_cache(record._ids[0], env)
                    if not hit:
                        try:
                            vals[name] = convert_to_read(
                                record[name], record, use_display_name
                            )
                        except MissingError:
                            vals.clear()
                        continue
                    try:
                        vals[name] = convert_to_read(
                            convert_to_record(cache_value, record),
                            record,
                            use_display_name,
                        )
                    except MissingError:
                        vals.clear()
                    except KeyError:
                        # Translation miss in translated Char/Text: fall back to
                        # the standard __get__ path, which handles it.
                        try:
                            vals[name] = convert_to_read(
                                record[name], record, use_display_name
                            )
                        except MissingError:
                            vals.clear()
            else:
                # Non-stored fields (computed, related, etc.) are not populated
                # by fetch(); they need Field.__get__ to trigger computation.
                convert = field.convert_to_read
                for record, vals in data:
                    if not vals:
                        continue
                    try:
                        vals[name] = convert(record[name], record, use_display_name)
                    except MissingError:
                        vals.clear()

        return [vals for record, vals in data if vals]

    def _fetch_field(self, field: Field) -> None:
        """Fetch ``field`` for ``self`` from the database into cache."""
        # determine which fields can be prefetched
        if self.env.context.get("prefetch_fields", True) and field.prefetch:
            fnames = [
                name
                for name, f in self._fields.items()
                # select fields with the same prefetch group
                if f.prefetch == field.prefetch
                # discard fields with groups that the user may not access
                if self._has_field_access(f, "read")
            ]
            if field.name not in fnames:
                fnames.append(field.name)
        else:
            fnames = [field.name]
        self.fetch(fnames)

    @api.private
    def fetch(self, field_names: Collection[str] | None = None) -> None:
        """Make sure the given fields are in memory for the records in ``self``,
        by fetching what is necessary from the database.  Non-stored fields are
        mostly ignored, except for their stored dependencies.

        :param field_names: a collection of field names to fetch, or ``None`` for
            all accessible fields marked with ``prefetch=True``
        :raise AccessError: if user is not allowed to access requested information

        This method is implemented thanks to methods :meth:`_search` and
        :meth:`_fetch_query`, and should not be overridden.
        """
        self = self._origin
        if not self or not (field_names is None or field_names):
            return

        prof = _OrmProfile(_orm_read)

        fields_to_fetch = self._determine_fields_to_fetch(
            field_names, ignore_when_in_cache=True
        )

        # first determine a query that satisfies the domain and access rules
        if any(field.column_type for field in fields_to_fetch):
            query = self._search([("id", "in", self.ids)], active_test=False)
        else:
            try:
                self.check_access("read")
            except MissingError:
                # Method fetch() should never raise a MissingError, but method
                # check_access() can, because it must read fields on self.
                # So we restrict 'self' to existing records (to avoid an extra
                # exists() at the end of the method).
                self = self.exists()
                self.check_access("read")
            if not fields_to_fetch:
                return
            query = self._as_query(ordered=False)

        # fetch the fields
        fetched = self._fetch_query(query, fields_to_fetch)

        if prof.debug:
            prof.stop()
            _orm_read.debug(
                "[%.3f ms] fetch %s: %d records, %d fields",
                prof.elapsed * 1000,
                self._name,
                len(self),
                len(fields_to_fetch),
            )

        # possibly raise exception for the records that could not be read
        if fetched != self:
            forbidden = (self - fetched).exists()
            if forbidden:
                msg = "read"
                raise self.env["ir.rule"]._make_access_error(msg, forbidden)

    def _determine_fields_to_fetch(
        self,
        field_names: Collection[str] | None = None,
        ignore_when_in_cache: bool = False,
    ) -> list[Field]:
        """Return the fields to fetch among the given field names, following the
        dependencies of computed fields.  Used by :meth:`fetch` and
        :meth:`search_fetch`.

        :param field_names: the collection of requested fields, or ``None`` for
            all accessible fields marked with ``prefetch=True``
        :param ignore_when_in_cache: skip fields already in cache for ``self``
        :return: the list of fields that must be fetched
        :raise AccessError: when fetching fields the user cannot access
        """
        if field_names is None:
            return [
                field
                for field in self._fields.values()
                if field.prefetch is True and self._has_field_access(field, "read")
            ]

        if not field_names:
            return []

        fields_to_fetch: list[Field] = []
        fields_todo: deque[Field] = deque()
        fields_done = {self._fields["id"]}  # trick: ignore 'id'
        for field_name in field_names:
            if not isinstance(field_name, str) or field_name not in self._fields:
                # Raise (not skip): only ``read()`` is lenient about unknown
                # fields, and it sanitizes its own input beforehand. Silently
                # dropping here turned ``fetch(["typo"])`` / ``search_fetch`` into
                # no-ops that mask caller bugs.
                raise ValueError(
                    f"Invalid field {field_name!r} on model {self._name!r}"
                )
            field = self._fields[field_name]
            self._check_field_access(field, "read")
            fields_todo.append(field)

        while fields_todo:
            field = fields_todo.popleft()
            if field in fields_done:
                continue
            fields_done.add(field)
            if ignore_when_in_cache and not any(field._cache_missing_ids(self)):
                # field is already in cache: don't fetch it
                continue
            if field.store:
                fields_to_fetch.append(field)
            else:
                # optimization: fetch field dependencies
                for dotname in self.pool.field_depends[field]:
                    dep_field = self._fields[dotname.split(".", 1)[0]]
                    if (not dep_field.store) or (
                        dep_field.prefetch is True
                        and self._has_field_access(dep_field, "read")
                    ):
                        fields_todo.append(dep_field)

        return fields_to_fetch

    def _fetch_query(self, query: Query, fields: Sequence[Field]) -> Self:
        """Fetch the given fields from the given query, cache them, and return
        the fetched records.

        This method may be overridden to change what fields to actually fetch,
        or to change the values that are put in cache.
        """
        prof = _OrmProfile(_orm_read)

        # determine columns fields and those with their own read() method
        column_fields: OrderedSet[Field] = OrderedSet()
        other_fields: OrderedSet[Field] = OrderedSet()
        for field in fields:
            if field.name == "id":
                continue
            # raise (not assert): holds under python -O; a non-stored field
            # would otherwise fail later at SQL generation with an opaque error.
            if not field.store:
                raise RuntimeError(f"_fetch_query expects stored fields, got {field}")
            (column_fields if field.column_type else other_fields).add(field)

        context = self.env.context

        # Backend dispatch: in-memory backend or PostgreSQL (None = SQL).
        if (backend := self.env.backend) is not None:
            return backend.fetch(self, query, column_fields, other_fields)

        if column_fields:
            # the query may involve several tables: we need fully-qualified names
            sql_terms = [SQL.identifier(self._table, "id")]
            for field in column_fields:
                sql = self._field_to_sql(self._table, field.name, query)
                if field.type == "binary" and (
                    context.get("bin_size") or context.get("bin_size_" + field.name)
                ):
                    # pg_size_pretty has (bigint) and (numeric) overloads; cast
                    # to disambiguate
                    sql = SQL("pg_size_pretty(length(%s)::bigint)", sql)
                elif not field.translate:
                    # An untranslated field need not flush its own pending write
                    # before being fetched: _insert_cache won't clobber the dirty
                    # cache value. (Translated fields stay in to_flush because
                    # their SQL reads/merges the stored jsonb column.)
                    to_flush = (f for f in sql.to_flush if f != field)
                    sql = SQL(sql.code, *sql.params, to_flush=to_flush)
                sql_terms.append(sql)

            # select the given columns from the rows in the query
            rows = self.env.execute_query(query.select(*sql_terms))
            prof.mark("sql")

            if not rows:
                return self.browse()

            # Transpose rows into per-column tuples; first column is the ids.
            column_values = zip(*rows, strict=False)
            ids = next(column_values)
            fetched = self.browse(ids)

            # Insert without overwriting: a pending update's value is assumed
            # cached, so we need not flush when fetched values don't clobber it.
            for field, values in zip(column_fields, column_values, strict=True):
                field._insert_cache(fetched, values)
            prof.mark("cache")
        else:
            fetched = self.browse(query)
            prof.mark("sql")
            prof.mark("cache")

        # process non-column fields
        if fetched:
            for field in other_fields:
                field.read(fetched)

        prof.stop()
        if prof.debug:
            _orm_read.debug(
                "[%.3f ms] _fetch_query %s: %d col + %d other fields -> %d rows"
                " | sql=%.1f cache=%.1f other=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(column_fields),
                len(other_fields),
                len(fetched),
                prof.ms("start", "sql"),
                prof.ms("sql", "cache"),
                prof.ms("cache", "end"),
            )

        return fetched

    def get_metadata(self) -> list[ValuesType]:
        """Return some metadata about the given records.

        :returns: list of ownership dictionaries for each requested record with the following keys:

            * id: object id
            * create_uid: user who created the record
            * create_date: date when the record was created
            * write_uid: last user who changed the record
            * write_date: date of the last change to the record
            * xmlid: XML ID to use to refer to this record (if there is one), in format ``module.name``
            * xmlids: list of dict with xmlid in format ``module.name``, and noupdate as boolean
            * noupdate: A boolean telling if the record will be updated or not
        """

        IrModelData = self.env["ir.model.data"].sudo()
        if self._log_access:
            res = self.read(LOG_ACCESS_COLUMNS)
        else:
            res = [{"id": x} for x in self.ids]

        xml_data = defaultdict(list)
        imds = IrModelData.search_read(
            [("model", "=", self._name), ("res_id", "in", self.ids)],
            ["res_id", "noupdate", "module", "name"],
            order="id DESC",
        )
        for imd in imds:
            xml_data[imd["res_id"]].append(
                {
                    "xmlid": f"{imd['module']}.{imd['name']}",
                    "noupdate": imd["noupdate"],
                }
            )

        for r in res:
            main = xml_data.get(r["id"], [{}])[-1]
            r["xmlid"] = main.get("xmlid", False)
            r["noupdate"] = main.get("noupdate", False)
            r["xmlids"] = xml_data.get(r["id"], [])[::-1]
        return res
