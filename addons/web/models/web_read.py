"""Web CRUD operations on the base model.

Provides ``web_read``, ``web_save``, ``web_search_read``, ``web_name_search``,
and ``web_resequence`` — the fundamental data-access methods consumed by the
webclient's relational model layer.
"""

from collections import defaultdict
from typing import Any

from odoo import api, models
from odoo.api import DomainType, NewId
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.fields import Datetime as FieldsDatetime
from odoo.tools import OrderedSet
from odoo.tools.cache_version import versioned, versioned_envelope


class lazymapping(defaultdict):
    """defaultdict whose factory receives the missing *key* as argument."""

    def __missing__(self, key: Any) -> Any:
        value = self.default_factory(key)
        self[key] = value
        return value


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    @api.readonly
    def web_name_search(
        self,
        name: str,
        specification: dict[str, dict],
        domain: DomainType | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[dict]:
        """Search by name and return records formatted per *specification*."""
        id_name_pairs = self.name_search(name, domain, operator, limit)
        if len(specification) == 1 and "display_name" in specification:
            # Batch-browse all IDs so singletons share one prefetch group,
            # reducing N isolated field reads to 1 batched SQL query.
            # ``.exists()`` so a record unlinked between name_search and this
            # browse is dropped here rather than raising MissingError on the
            # ``rec.display_name`` read below — which would 500 the whole RPC
            # before the graceful ``formatted_map.get(id, name)`` fallback could
            # apply.
            records = (
                self.with_context(formatted_display_name=True)
                .browse([id for id, _ in id_name_pairs])
                .exists()
            )
            formatted_map = {rec.id: rec.display_name for rec in records}
            return [
                {
                    "id": id,
                    "display_name": name,
                    # Fall back to the name_search name if the record vanished
                    # between name_search and this browse (concurrent unlink),
                    # or display_name iteration skipped it — a missing key would
                    # 500 the whole RPC instead of degrading gracefully.
                    "__formatted_display_name": formatted_map.get(id, name),
                }
                for id, name in id_name_pairs
            ]
        records = self.browse([id for id, _ in id_name_pairs])
        return records.web_read(specification)

    @api.model
    @api.readonly
    @versioned
    def web_search_read(
        self,
        domain: DomainType,
        specification: dict[str, dict],
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        count_limit: int | None = None,
    ) -> dict[str, int | list]:
        """Search records and return them formatted per *specification*."""
        # Unknown-field policy at the web boundary: screen the specification
        # the same way ``web_read`` effectively tolerates stale names —
        # ``read()`` drops unknown fields with a warning and web_read's
        # relational loop skips them — so the response simply lacks that key.
        # Without screening, ``_determine_fields_to_fetch`` below is strict
        # and a single stale name in a cached view's spec 500s the whole call.
        specification = self._screen_fields_spec(specification)
        # Build the search query once — domain processing + access rules.
        # We retain the query to reuse its FROM/WHERE for the count,
        # avoiding the overhead of a second _search() call.
        query = self._search(
            domain, offset=offset, limit=limit, order=order or self._order
        )
        if query.is_empty():
            if not self.env.su:
                self._determine_fields_to_fetch(specification.keys())
            return {"length": 0, "records": []}

        fields_to_fetch = self._determine_fields_to_fetch(specification.keys())
        records = self._fetch_query(query, fields_to_fetch)
        values_records = records.web_read(specification)
        return self._format_web_search_read_results(
            domain,
            values_records,
            offset,
            limit,
            count_limit,
            _query=query,
        )

    def _format_web_search_read_results(
        self,
        domain: DomainType,
        records: list[dict],
        offset: int = 0,
        limit: int | None = None,
        count_limit: int | None = None,
        _query: Any = None,
    ) -> dict[str, int | list]:
        """Wrap *records* with a length estimate for pager support."""
        if not records:
            if not offset:
                # Genuinely empty result set.
                return {"length": 0, "records": []}
            # Empty page PAST the end of the result set — e.g. records were
            # deleted under a user paged to offset > 0. Records still exist on
            # earlier pages, so returning length 0 would collapse the pager and
            # hide them. Compute the real count instead (reusing the data
            # query's FROM/WHERE when available).
            if _query is not None:
                length = _query.count_matching(count_limit)
            else:
                length = self.search_count(domain, limit=count_limit)
            return {"length": length, "records": []}
        current_length = len(records) + offset
        limit_reached = len(records) == limit
        force_search_count = self.env.context.get("force_search_count")
        count_limit_reached = count_limit and count_limit <= current_length
        if limit and (
            (limit_reached and not count_limit_reached) or force_search_count
        ):
            if _query is not None:
                # Reuse the data query's FROM/WHERE — same joins, same
                # filters — instead of rebuilding via search_count().
                length = _query.count_matching(count_limit)
            else:
                length = self.search_count(domain, limit=count_limit)
        else:
            length = current_length
        return {
            "length": length,
            "records": records,
        }

    def web_save(
        self,
        vals,
        specification: dict[str, dict],
        next_id=None,
        last_write_date=None,
        known_values=None,
    ) -> list[dict]:
        """Create or write a record and return it formatted per *specification*.

        Optimistic concurrency control:

        * *known_values* — the fields being written, as the client originally
          read them, for a **field-scoped** check: ``UserError`` is raised only
          if one of *those* fields was changed on the server since the client
          read it. Concurrent writes to *other* fields (e.g. stored-compute
          recomputations triggered by related records) touch disjoint columns,
          cannot cause a lost update, and are ignored. The comparison is
          type-aware and fails OPEN — any field that cannot be safely compared
          is skipped rather than risk a false conflict. Two shapes, chosen by
          record count: a singleton passes a flat ``{field: baseline}``; a
          list mass-edit (same *vals* to several records) passes per-record
          ``{id: {field: baseline}}`` so each record is checked against its own
          baseline in one bulk query.
        * *last_write_date* — legacy / urgent (sendBeacon) fallback: a coarser
          row-level ``write_date`` check.

        Both prevent silent data loss from concurrent edits; the field-scoped
        path additionally avoids false conflicts from unrelated background
        writes.
        """
        self._validate_web_save_vals(vals)
        if self:
            # web_save supports a multi-record set: the list view mass-edit calls
            # it with several ids (dynamic_list._multiSave -> webSave, non-x2many
            # branch). Only the concurrency-checked paths below require a singleton.
            if known_values is not None:
                # Disambiguate by SHAPE, not record count. The flat singleton
                # form ``{field: baseline}`` has field names as keys; the
                # per-record mass-edit form ``{id: {field: baseline}}`` has
                # record ids. Keying off ``len(self) == 1`` misrouted a
                # single-SELECTED-row list mass-edit — which always sends the
                # per-record shape, even for one row (dynamic_list._multiSave) —
                # into the singleton check, where the record-id key matches no
                # field name so the guard silently no-opped and a concurrent
                # edit was lost. Field names are identifiers and record ids are
                # numeric, so key numericness separates the two shapes.
                #
                # Disambiguate on that numericness, NOT on ``k in self._fields``:
                # the latter misroutes a *singleton* whose keys include a stale
                # field name (an outdated cached form view still referencing a
                # removed field) into the multi branch, where every field-name
                # key fails ``int()`` coercion -> empty baselines -> the
                # lost-update check silently no-ops and a concurrent edit is
                # lost. Record ids are always numeric; field names never are, so
                # this tolerates unknown field names, which the singleton check
                # already skips (see ``_concurrency_checkable_fields``).
                is_multi = known_values and all(
                    str(k).lstrip("-").isdigit() for k in known_values
                )
                if known_values and not is_multi:
                    self._check_concurrent_field_changes(vals, known_values)
                else:
                    self._check_concurrent_field_changes_multi(vals, known_values)
            elif last_write_date and "write_date" in self._fields:
                # Row-level write_date check reads ``self.id`` directly: this is a
                # single-record (urgent sendBeacon) path, so enforce the singleton.
                self.ensure_one()
                # Read directly from DB to avoid ORM cache (which may be stale
                # if another user's write happened in a different transaction).
                self.env.cr.execute(
                    'SELECT write_date FROM "%s" WHERE id = %%s' % self._table,
                    (self.id,),
                )
                row = self.env.cr.fetchone()
                server_write_date = row[0] if row else None
                # to_datetime handles ISO strings with timezone offsets
                # (e.g., "2026-03-19T16:09:18.000-06:00" from the JS
                # client), converting to naive UTC automatically.
                client_dt = FieldsDatetime.to_datetime(last_write_date)
                # Normalize server side to naive UTC as well.
                if server_write_date and getattr(server_write_date, "tzinfo", None):
                    server_write_date = server_write_date.replace(tzinfo=None)
                # Truncate to seconds — the JS client sends write_date
                # with .000 milliseconds, losing the microsecond precision
                # that PostgreSQL stores.  Without this, the server value
                # is always ~0-1s "newer" and every save triggers a false
                # concurrency error.
                if server_write_date:
                    server_write_date = server_write_date.replace(microsecond=0)
                if client_dt:
                    client_dt = client_dt.replace(microsecond=0)
                if server_write_date and client_dt and server_write_date > client_dt:
                    # A stale read is deterministic, not a transient DB
                    # conflict: retrying re-runs the request with the SAME
                    # client write_date against a server write_date that only
                    # moves forward, so it can never succeed. Raise UserError
                    # (which retrying() does not catch) to fail fast and tell
                    # the user to reload — NOT ConcurrencyError, whose upstream
                    # contract marks it retryable, so retrying() would burn its
                    # ~5x exponential backoff (~10-30s) before failing anyway.
                    raise UserError(
                        "This record was modified by another user.\n"
                        "Please reload and re-apply your changes."
                    )
            self.write(vals)
            record = self
        else:
            record = self.create(vals)
        if next_id:
            record = self.browse(next_id)
        return record.with_context(bin_size=True).web_read(specification)

    # x2many commands whose second element is the id of an EXISTING database
    # row (UPDATE/DELETE/UNLINK/LINK); SET carries its id list in the third
    # element. CREATE's second element is a client-side placeholder (0 /
    # virtual ref) that never reaches SQL, so it is exempt.
    _X2M_ROW_ID_COMMANDS = (
        Command.UPDATE,
        Command.DELETE,
        Command.UNLINK,
        Command.LINK,
    )

    def _validate_web_save_vals(self, vals: dict) -> None:
        """Validate client-supplied *vals* at the web boundary, before write().

        Two cheap checks against raw client JSON, both raising a clean,
        translated ``UserError`` instead of an opaque 500:

        * Unknown field names (a stale cached form view still referencing a
          field removed by a module upgrade) — the write would otherwise die
          in a raw KeyError. The values are deliberately NOT silently dropped
          (unlike read paths, which degrade): discarding user-entered data on
          save is worse than failing, so the user is told to reload.
        * Non-integer row ids in x2many command lists — the JS model can leak
          a virtual id (e.g. ``[1, "virtual_zz", {...}]``), which otherwise
          reaches SQL and fails as a raw psycopg error. Shallow on purpose:
          only the command lists themselves are inspected, never the nested
          command vals.
        """
        unknown = [name for name in vals if name not in self._fields]
        if unknown:
            raise UserError(
                self.env._(
                    "This form is out of date and references field(s) that no "
                    "longer exist (%s). Your changes were not saved — please "
                    "reload the page and re-apply them.",
                    ", ".join(unknown),
                )
            )
        for name, value in vals.items():
            field = self._fields[name]
            if field.type not in ("one2many", "many2many") or not isinstance(
                value, (list, tuple)
            ):
                continue
            for command in value:
                if not isinstance(command, (list, tuple)) or len(command) < 2:
                    continue
                if command[0] in self._X2M_ROW_ID_COMMANDS:
                    row_ids = (command[1],)
                elif (
                    command[0] == Command.SET
                    and len(command) > 2
                    and isinstance(command[2], (list, tuple))
                ):
                    row_ids = command[2]
                else:
                    continue
                for row_id in row_ids:
                    # bool is an int subclass; True/False are not valid row ids.
                    if not isinstance(row_id, int) or isinstance(row_id, bool):
                        raise UserError(
                            self.env._(
                                'Invalid record reference %(row_id)r in field "'
                                '%(field)s". Your changes were not saved — '
                                "please reload the page and re-apply them.",
                                row_id=row_id,
                                field=field.string or name,
                            )
                        )

    # Only unambiguous primitives + many2one (compared by id) are concurrency-
    # checkable. date/datetime are deliberately excluded: their client
    # serialization (Luxon, tz/ms) vs the raw DB value risks a timezone-boundary
    # mismatch — a *false* conflict, the very thing this check exists to avoid.
    # jsonb-backed columns (translated / company-dependent fields) are excluded
    # for the same reason: the raw DB value is a per-lang / per-company dict, not
    # the scalar the client read. Excluded types fall through unchecked (fail open).
    _CONCURRENCY_SAFE_TYPES = frozenset(
        (
            "integer",
            "boolean",
            "char",
            "text",
            "selection",
            "float",
            "monetary",
            "many2one",
        )
    )

    def _concurrency_checkable_fields(self, vals):
        """Field names in *vals* whose value can be safely concurrency-checked
        (model-level: independent of which record). See _CONCURRENCY_SAFE_TYPES.
        """
        return [
            n
            for n in vals
            if n in self._fields
            and self._fields[n].store
            and self._fields[n].column_type
            and self._fields[n].column_type[0] != "jsonb"
            and self._fields[n].type in self._CONCURRENCY_SAFE_TYPES
        ]

    def _field_concurrently_modified(self, name, server_raw, baseline_raw, new_raw):
        """True iff the server moved *name* away from the client's baseline AND
        the user's write would not land on the server's current value anyway.

        Type-aware and fails OPEN: any value that cannot be safely coerced is
        treated as non-conflicting rather than risk a false positive. Shared by
        the singleton and multi-record concurrency checks so their comparison
        semantics can never drift.
        """
        try:
            field = self._fields[name]
            current = self._coerce_concurrency_value(field, server_raw)
            baseline = self._coerce_concurrency_value(field, baseline_raw)
            new = self._coerce_concurrency_value(field, new_raw)
            return current not in (baseline, new)
        except Exception:
            # Fail OPEN: any value we cannot safely coerce is treated as
            # non-conflicting rather than risk a false positive.
            return False

    def _check_concurrent_field_changes(self, vals, known_values):
        """Field-scoped optimistic lock for a SINGLE record :meth:`web_save`.

        Raise ``UserError`` if a field being written (*vals*) was changed on the
        server since the client read it (*known_values* is the client's flat
        ``{field: baseline}`` map). Concurrent writes to *other* fields are
        ignored — they touch disjoint columns and cannot lose the user's edit.
        """
        self.ensure_one()
        names = [
            n for n in self._concurrency_checkable_fields(vals) if n in known_values
        ]
        if not names:
            return
        # Read current values straight from the DB, bypassing the ORM cache
        # (which may be stale w.r.t. a write committed by another transaction)
        # — same rationale as the legacy write_date check.
        cols = ", ".join('"%s"' % n for n in names)
        self.env.cr.execute(
            'SELECT %s FROM "%s" WHERE id = %%s' % (cols, self._table),
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            return
        conflicts = [
            self._fields[name].string or name
            for name, server_raw in zip(names, row, strict=True)
            if self._field_concurrently_modified(
                name, server_raw, known_values[name], vals[name]
            )
        ]
        if conflicts:
            raise UserError(
                self.env._(
                    "This record was modified by another user while you were "
                    "editing it.\nConflicting field(s): %s.\n"
                    "Please reload and re-apply your changes.",
                    ", ".join(conflicts),
                )
            )

    def _check_concurrent_field_changes_multi(self, vals, known_values):
        """Per-record field-scoped optimistic lock for a MULTI-record
        :meth:`web_save` (list mass-edit: the SAME *vals* written to every
        record, each carrying its OWN baseline). *known_values* is
        ``{id: {field: baseline}}``.
        """
        # Same vals written to every record: map each id to that shared dict.
        self._check_concurrent_field_changes_records(
            dict.fromkeys(self.ids, vals), known_values
        )

    def _check_concurrent_field_changes_multi_list(self, vals_list, known_values):
        """Per-record field-scoped optimistic lock for :meth:`web_save_multi`,
        where each record has its OWN *vals* (a relative Field Operation, e.g.
        ``qty += 5``, resolves client-side to a distinct absolute value per
        record). *vals_list* is aligned with ``self``; *known_values* is
        ``{id: {field: baseline}}``.
        """
        self._check_concurrent_field_changes_records(
            dict(zip(self.ids, vals_list, strict=True)), known_values
        )

    def _check_concurrent_field_changes_records(self, vals_by_id, known_values):
        """Core per-record field-scoped optimistic lock. *vals_by_id* maps each
        record id to the vals being written to IT — shared by the mass-edit
        (same vals everywhere) and :meth:`web_save_multi` (per-record vals)
        callers so their comparison semantics can never drift.

        One bulk ``SELECT`` reads every record's current values (no N+1: the
        query is batched over the whole set); the comparison is then in-memory
        and reuses the exact same per-field semantics as the singleton path,
        failing OPEN per (record, field). A record with no baseline is skipped.
        Concurrent writes to other fields, or to the value the user is writing
        anyway, are ignored.
        """
        if not vals_by_id:
            return
        # Checkable fields are model-level (depend on the field TYPE, not the
        # value), so the union of written keys covers a per-record vals that
        # writes a field the others don't.
        all_keys = set().union(*(v.keys() for v in vals_by_id.values()))
        checkable = self._concurrency_checkable_fields(dict.fromkeys(all_keys))
        if not checkable:
            return
        # JSON serializes integer dict keys as strings; normalize back to ints.
        # ``known_values`` is client-supplied: skip any key that cannot be
        # int-coerced rather than raise (a 500) — consistent with this check's
        # documented fail-open contract.
        baselines = {}
        for rec_id, base in known_values.items():
            try:
                baselines[int(rec_id)] = base
            except TypeError, ValueError:
                continue
        cols = ", ".join('"%s"' % n for n in checkable)
        # ``= ANY(%s)`` with a list (psycopg3 adapts it to a Postgres array) —
        # one bulk read for the whole set, no N+1.
        self.env.cr.execute(
            'SELECT id, %s FROM "%s" WHERE id = ANY(%%s)' % (cols, self._table),
            (list(self.ids),),
        )
        current = {
            row[0]: dict(zip(checkable, row[1:], strict=True))
            for row in self.env.cr.fetchall()
        }
        conflict_ids = set()
        conflict_fields = set()
        for rec_id, server_row in current.items():
            baseline = baselines.get(rec_id)
            vals = vals_by_id.get(rec_id)
            if not baseline or not vals:
                continue  # fail open: no baseline (or no vals) for this record
            for name in checkable:
                if name not in baseline or name not in vals:
                    continue
                if self._field_concurrently_modified(
                    name, server_row[name], baseline[name], vals[name]
                ):
                    conflict_ids.add(rec_id)
                    conflict_fields.add(self._fields[name].string or name)
        if conflict_ids:
            raise UserError(
                self.env._(
                    "%(count)s of the records you edited were modified by another "
                    "user in the meantime.\nConflicting field(s): %(fields)s.\n"
                    "Please reload and re-apply your changes.",
                    count=len(conflict_ids),
                    fields=", ".join(sorted(conflict_fields)),
                )
            )

    @staticmethod
    def _coerce_concurrency_value(field, value):
        """Normalise *value* to a canonical primitive for concurrency compare.

        Handles the client's serialized form (m2o as ``{id, display_name}``,
        dates as ISO strings) and the raw DB form (m2o as FK id, dates as
        ``date`` objects) to the same primitive so equal values compare equal.
        """
        ftype = field.type
        if value is None or value is False:
            return {
                "integer": 0,
                "float": 0.0,
                "monetary": 0.0,
                "boolean": False,
                "many2one": False,
            }.get(ftype, "")
        if ftype == "many2one":
            if isinstance(value, dict):
                return value.get("id") or False
            if isinstance(value, (list, tuple)):
                return value[0] if value else False
            return int(value) if isinstance(value, (int, float)) else False
        if ftype == "integer":
            return int(value)
        if ftype in ("float", "monetary"):
            return round(float(value), 6)
        if ftype == "boolean":
            return bool(value)
        # char, text, selection
        return str(value)

    def web_save_multi(
        self,
        vals_list: list[dict],
        specification: dict[str, dict],
        known_values=None,
    ) -> list[dict]:
        """Write multiple records at once and return them formatted.

        Groups records with identical vals dicts and issues a single
        ``write()`` per group, amortising access-check, ``modified()``,
        and validation overhead.  Records with unhashable vals (x2many
        commands) fall back to individual writes.

        *known_values* (``{id: {field: baseline}}``) enables the same
        field-scoped optimistic concurrency check as :meth:`web_save`, but
        per-record: this path carries a DISTINCT vals per record (a relative
        Field Operation resolves to a different absolute value for each), so
        each record is checked against its own vals and baseline. The check
        runs BEFORE any write.
        """
        if len(self) != len(vals_list):
            msg = "Each record must have a corresponding vals entry."
            raise ValueError(msg)

        for vals in vals_list:
            self._validate_web_save_vals(vals)

        if known_values is not None:
            self._check_concurrent_field_changes_multi_list(vals_list, known_values)

        # Group records sharing identical vals — one write() per group
        # instead of one per record.  Preserves prefetch set via
        # with_prefetch() so reads inside write() stay batched.
        groups: dict[frozenset, list[int]] = {}
        vals_by_key: dict[frozenset, dict] = {}
        for record, vals in zip(self, vals_list, strict=True):
            try:
                key = frozenset(vals.items())
            except TypeError:
                # Unhashable values (x2many commands) — write individually
                record.write(vals)
                continue
            if key not in groups:
                groups[key] = []
                vals_by_key[key] = vals
            groups[key].append(record.id)

        prefetch_ids = self._prefetch_ids
        for key, ids in groups.items():
            self.browse(ids).with_prefetch(prefetch_ids).write(vals_by_key[key])

        return self.with_context(bin_size=True).web_read(specification)

    @api.readonly
    @versioned_envelope
    def web_read(self, specification: dict[str, dict]) -> list[dict]:
        """Read records and recursively resolve sub-specifications.

        This is the main entry point used by the webclient to fetch record
        data.  It handles many2one, x2many, reference, many2one_reference,
        and properties fields by recursively calling ``web_read`` on
        co-records according to *specification*.
        """
        fields_to_read = list(specification) or ["id"]

        if set(fields_to_read) == {"id"}:
            # id-only spec: ids are already known, so skip self.read()
            # entirely — this also sidesteps the co-model's access rules,
            # which may differ from self's. Normalize NewId → origin/False here
            # too (as ``cleanup`` does for the read() path), so a recursive
            # id-only sub-spec on unsaved records never leaks a raw NewId.
            values_list = [
                {"id": (id_.origin or False) if isinstance(id_, NewId) else id_}
                for id_ in self._ids
            ]
        else:
            values_list: list[dict] = self.read(fields_to_read, load=None)

        if not values_list:
            return values_list

        def cleanup(vals: dict) -> dict:
            """Fixup vals['id'] of a new record."""
            if not vals["id"]:
                vals["id"] = vals["id"].origin or False
            return vals

        for field_name, field_spec in specification.items():
            field = self._fields.get(field_name)
            if field is None:
                continue

            if field.type == "many2one":
                if "fields" not in field_spec:
                    for values in values_list:
                        if isinstance(values[field_name], NewId):
                            values[field_name] = values[field_name].origin or False
                    continue

                # Normalize NewId → origin before sub-spec processing;
                # NewId.__bool__ is False so they'd be excluded from co_ids
                # but the `is False` guard below wouldn't catch them → KeyError.
                for values in values_list:
                    if isinstance(values[field_name], NewId):
                        values[field_name] = values[field_name].origin or False

                # Extract co-record IDs directly from already-fetched values
                # instead of re-traversing the cache via self[field_name].
                co_ids = OrderedSet(
                    vals[field_name] for vals in values_list if vals[field_name]
                )
                co_records = self.env[field.comodel_name].browse(co_ids)
                if "context" in field_spec:
                    co_records = co_records.with_context(**field_spec["context"])

                extra_fields = dict(field_spec["fields"])
                extra_fields.pop("display_name", None)

                # Drop co-records the user cannot read (record rules) *before*
                # web_read, so a single restricted many2one target does not
                # raise AccessError and abort the WHOLE parent read — the
                # x2many branch below already does this; the many2one branch
                # used to abort instead of degrading to a name-only fallback.
                #
                # display_name is read from this SAME accessible subset, NOT
                # from ``co_records.sudo()``: reading the name of a target the
                # user cannot see leaks record-rule-restricted data (e.g. a
                # partner hidden by a multi-company rule is directly
                # AccessError, yet its name would still surface here). A
                # restricted target instead degrades to an empty value (the
                # ``or False`` below), the same as any other unreadable m2o.
                if co_records:
                    # _filtered_access already returns an order-preserving
                    # accessible subset, so no manual browse rebuild is needed.
                    # active_test=False widens _filtered_access to also vet
                    # archived targets; restore the original context before the
                    # recursive read so the sub-spec never runs under a leaked
                    # active_test=False (mirrors the x2many branch below).
                    readable_records = (
                        co_records.with_context(active_test=False)
                        ._filtered_access("read")
                        .with_context(co_records.env.context)
                    )
                else:
                    readable_records = co_records

                many2one_data = {
                    vals["id"]: cleanup(vals)
                    for vals in readable_records.web_read(extra_fields)
                }

                if "display_name" in field_spec["fields"]:
                    for rec in readable_records:
                        many2one_data.setdefault(rec.id, {"id": rec.id})[
                            "display_name"
                        ] = rec.display_name

                for values in values_list:
                    if values[field_name] is False:
                        continue
                    vals = many2one_data.get(values[field_name])
                    # A target with no sub-field data (inaccessible, sub-fields
                    # dropped) still resolves to at least its id/display_name.
                    # ``or False`` so an inaccessible target with no display_name
                    # yields False (empty m2o), matching every other empty path,
                    # rather than None (JSON null).
                    values[field_name] = (vals and vals["id"] and vals) or False

            elif field.type in ("one2many", "many2many"):
                if not field_spec:
                    continue

                # Extract co-record IDs directly from already-fetched values
                # instead of re-traversing the cache via self[field_name].
                co_ids = OrderedSet(
                    id_ for vals in values_list for id_ in vals[field_name]
                )
                co_records = self.env[field.comodel_name].browse(co_ids)

                if field_spec.get("order"):
                    # Include the field's context when reapplying to preserve settings like active_test=False
                    field_context = field.context or {}
                    if not (
                        co_records
                        and co_records.env["ir.model.access"].check(
                            co_records._name, "read", raise_exception=False
                        )
                    ):
                        # If the comodel is not readable, keep the x2many empty.
                        co_records = co_records.browse()
                    else:
                        try:
                            co_records = (
                                co_records.with_context(active_test=False)
                                .search(
                                    [("id", "in", co_records.ids)],
                                    order=field_spec["order"],
                                )
                                # Reapply the original RPC context (dropping the
                                # active_test=False used only for the search),
                                # then layer the field's own context on top.
                                # Positional dict + kwargs so a key present in
                                # BOTH (e.g. active_test on res.partner.child_ids)
                                # is OVERRIDDEN by field_context, not passed twice
                                # — the **env.context/**field_context double-splat
                                # raised TypeError on any shared key.
                                .with_context(co_records.env.context, **field_context)
                            )
                        # Degrade to an empty list on any failure the ordered
                        # search can raise: AccessError/UserError (model rejects
                        # the search, e.g. account.code.mapping) OR ValueError (a
                        # client ``order`` spec on a non-stored field — "Cannot
                        # convert to SQL because it is not stored"). Letting the
                        # ValueError escape would 500 the whole parent read,
                        # while the sibling failure modes here already degrade.
                        except AccessError, UserError, ValueError:
                            co_records = co_records.browse()
                    order_key = {
                        co_record.id: index
                        for index, co_record in enumerate(co_records)
                    }
                    for values in values_list:
                        # Keep only ids present in order_key: drops both
                        # inaccessible co-records and any stale ids left over
                        # from cache reuse across records.
                        values[field_name] = [
                            id_ for id_ in values[field_name] if id_ in order_key
                        ]
                        values[field_name] = sorted(
                            values[field_name], key=order_key.__getitem__
                        )
                elif "fields" in field_spec:
                    # Drop co-records the user cannot read (record rules) *before*
                    # web_read, so a single restricted co-record does not raise
                    # AccessError and abort the whole read. The ``order`` branch
                    # above gets this filtering for free via ``search``; this
                    # branch must do it explicitly. Only filter when the comodel
                    # is readable at all; otherwise keep the relation ids
                    # unchanged (e.g. hr.employee referenced from hr.appraisal for
                    # a base.group_user).
                    if co_records and co_records.env["ir.model.access"].check(
                        co_records._name, "read", raise_exception=False
                    ):
                        accessible = co_records.with_context(
                            active_test=False
                        )._filtered_access("read")
                        accessible_ids = set(accessible.ids)
                        for values in values_list:
                            values[field_name] = [
                                id_
                                for id_ in values[field_name]
                                if id_ in accessible_ids
                            ]
                        co_records = accessible.with_context(co_records.env.context)

                if "context" in field_spec:
                    co_records = co_records.with_context(**field_spec["context"])

                if "fields" in field_spec:
                    if field_spec.get("limit") is not None:
                        limit = field_spec["limit"]
                        ids_to_read = OrderedSet(
                            id_
                            for values in values_list
                            for id_ in values[field_name][:limit]
                        )
                        co_records = co_records.browse(ids_to_read)

                    x2many_data = {
                        vals["id"]: vals
                        for vals in co_records.web_read(field_spec["fields"])
                    }

                    for values in values_list:
                        values[field_name] = [
                            x2many_data.get(id_, {"id": id_})
                            for id_ in values[field_name]
                        ]

            elif field.type in ("reference", "many2one_reference"):
                if not field_spec:
                    continue

                values_by_id = {vals["id"]: vals for vals in values_list}
                has_sub_fields = "fields" in field_spec
                # Non-trivial sub-fields let us infer existence from
                # web_read results (id-only spec short-circuits without
                # hitting the DB, so it cannot detect deleted records).
                can_infer_existence = has_sub_fields and any(
                    fname != "id" for fname in field_spec["fields"]
                )

                # --- First pass: collect co-records grouped by model ---
                # Field values are already in cache from the earlier
                # self.read(), so record[field_name] is free.
                co_by_model = defaultdict(list)  # model → [(record_id, co_id)]
                for record in self:
                    if record.id not in values_by_id:
                        # Concurrently unlinked between self.read() and here: it
                        # never entered values_list, so there is no row to
                        # annotate. Every downstream ``values_by_id[record.id]``
                        # (including the many2one_reference reset below and the
                        # second pass) would otherwise KeyError.
                        continue
                    if not record[field_name]:
                        continue
                    if field.type == "reference":
                        co_rec = record[field_name]
                        co_by_model[co_rec._name].append((record.id, co_rec.id))
                    else:  # many2one_reference
                        if not record[field.model_field]:
                            values_by_id[record.id][field_name] = False
                            continue
                        co_by_model[record[field.model_field]].append(
                            (record.id, record[field_name])
                        )

                # --- Batch web_read / exists() per model ---
                for model_name, pairs in co_by_model.items():
                    co_ids = list({co_id for _, co_id in pairs})
                    CoModel = self.env[model_name]
                    if "context" in field_spec:
                        CoModel = CoModel.with_context(**field_spec["context"])
                    co_recordset = CoModel.browse(co_ids)

                    co_data = {}
                    if has_sub_fields:
                        try:
                            co_data = {
                                d["id"]: d
                                for d in co_recordset.web_read(field_spec["fields"])
                            }
                        except AccessError:
                            # Per-record fallback: some records may be accessible
                            for co_id in co_ids:
                                try:
                                    result = CoModel.browse(co_id).web_read(
                                        field_spec["fields"]
                                    )
                                    if result:
                                        co_data[co_id] = result[0]
                                except AccessError:
                                    co_data[co_id] = {
                                        "id": co_id,
                                        "display_name": self.env._(
                                            "You don't have access to this record"
                                        ),
                                    }

                    existing_ids = (
                        set(co_data)
                        if can_infer_existence
                        else set(co_recordset.exists().ids)
                    )

                    for record_id, co_id in pairs:
                        record_values = values_by_id[record_id]
                        if co_id not in existing_ids:
                            record_values[field_name] = False
                            if field.type == "many2one_reference":
                                record_values[field.model_field] = False
                            continue
                        if has_sub_fields and co_id in co_data:
                            record_values[field_name] = co_data[co_id]
                            if field.type == "reference":
                                record_values[field_name]["id"] = {
                                    "id": co_id,
                                    "model": model_name,
                                }

            elif field.type == "properties":
                if not field_spec or "fields" not in field_spec:
                    continue

                prop_ctx = field_spec.get("context")

                # --- Collect all property co-record IDs for batching ---
                # Key: (comodel, property_name) → set of co-record IDs
                batch_ids: dict[tuple[str, str], set[int]] = defaultdict(set)
                batch_specs: dict[str, dict] = {}  # property_name → spec['fields']

                for values in values_list:
                    for property_name, spec in field_spec["fields"].items():
                        if "fields" not in spec:
                            continue
                        prop = next(
                            (
                                p
                                for p in values[field_name]
                                if p.get("name") == property_name
                            ),
                            None,
                        )
                        if not prop or not prop.get("comodel") or not prop.get("value"):
                            continue
                        comodel = prop["comodel"]
                        batch_specs[property_name] = spec["fields"]
                        if prop.get("type") == "many2one":
                            batch_ids[(comodel, property_name)].add(prop["value"][0])
                        elif prop.get("type") == "many2many":
                            batch_ids[(comodel, property_name)].update(
                                r[0] for r in prop["value"]
                            )

                # --- Batch web_read per (comodel, property_name) ---
                co_data: dict[tuple[str, str], dict[int, dict]] = {}
                for (comodel, prop_name), ids in batch_ids.items():
                    co_records = (
                        self.env[comodel].with_context(**(prop_ctx or {})).browse(ids)
                    )
                    co_data[(comodel, prop_name)] = {
                        d["id"]: d for d in co_records.web_read(batch_specs[prop_name])
                    }

                # --- Distribute results ---
                for values in values_list:
                    old_values = values[field_name]
                    next_values = []
                    for property_name, spec in field_spec["fields"].items():
                        prop = next(
                            (p for p in old_values if p.get("name") == property_name),
                            None,
                        )
                        if not prop:
                            continue

                        comodel = prop.get("comodel")
                        if comodel and prop.get("value") and "fields" in spec:
                            data = co_data.get((comodel, property_name), {})
                            if prop.get("type") == "many2one":
                                co_id = prop["value"][0]
                                if co_id in data:
                                    # prop["value"] must stay a list; replace its
                                    # plain [id, display_name] with the full
                                    # web_read dict, still wrapped in a list.
                                    prop["value"] = [data[co_id]]
                            elif prop.get("type") == "many2many":
                                prop["value"] = [
                                    data.get(r[0], r) for r in prop["value"]
                                ]

                        next_values.append(prop)

                    values[field_name] = next_values

        return values_list

    def web_resequence(
        self,
        specification: dict[str, dict],
        field_name: str = "sequence",
        offset: int = 0,
    ) -> list[dict]:
        """Re-sequences a number of records in the model, by their ids.

        The re-sequencing starts at the first record of ``ids``, the
        sequence number starts at ``offset`` and is incremented by one
        after each record.

        The returning value is a read of the resequenced records with
        the specification given in the parameter.

        :param specification: specification for the read of the
            resequenced records
        :param field_name: field used for sequence specification,
            defaults to ``"sequence"``
        :param offset: sequence number for first record in ``ids``,
            allows starting the resequencing from an arbitrary number,
            defaults to ``0``
        """
        if field_name not in self._fields:
            return []
        if not self:
            return []

        field = self._fields[field_name]

        # Fast path eligibility. The cache-dirty path below skips ``write()``
        # entirely, so it is only correct when nothing observes the write:
        #   - the model must not override ``write`` (guards, tracking, cache
        #     invalidation all live inside it);
        #   - the field must be a plain stored Integer with no ``inverse``
        #     (an inverse must run) and no ``compute`` (computed fields are not
        #     written this way).
        # Otherwise fall back to per-record ``write()`` so overrides, inverses
        # and mail tracking all fire — same semantics as a manual edit.
        fast_path = (
            type(self).write is models.BaseModel.write
            and field.store
            and field.type == "integer"
            and not field.compute
            and not field.inverse
        )

        if not fast_path:
            for i, record in enumerate(self, start=offset):
                record.write({field_name: i})
            return self.web_read(specification)

        # Access checks — once for all records instead of once per write()
        self.check_access("write")
        self._check_field_access(field, "write")

        # Set log-access fields once on the full recordset
        if self._log_access:
            self._fields["write_uid"].mark_dirty(self, self.env.uid)
            self._fields["write_date"].mark_dirty(self, self.env.cr.now())

        # Mark each record's sequence value as dirty (cache-only, no SQL yet)
        for i, record in enumerate(self, start=offset):
            field.mark_dirty(record, i)

        # Trigger recomputation of dependent fields — once for all records
        self.modified([field_name])

        # Validate constraints — once for all records
        self._validate_fields([field_name])

        if self._check_company_auto:
            self._check_company([field_name])

        return self.web_read(specification)
