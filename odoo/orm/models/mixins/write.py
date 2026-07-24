"""Record update: ``write`` and its SQL-supporting helpers.

Split out of the former CrudMixin; see _crud_common.py for shared
constants. Copy/duplication lives in copy.py (CopyMixin).
"""

import typing
from collections import defaultdict
from itertools import batched
from typing import Self

from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL
from odoo.tools.nplusone import _n1_enabled
from odoo.tools.orm_profiler import _OrmProfile
from odoo.tools.translate import _

from ..._typing import ValuesType
from ...primitives import UPDATE_BATCH_SIZE
from ._crud_common import (
    _orm_crud,
    bad_field_names,
)
from ._model_stubs import _ModelStubs


class WriteMixin(_ModelStubs):
    """Record update: ``write`` and its SQL-supporting helpers."""

    __slots__ = ()

    def write(self, vals: ValuesType) -> typing.Literal[True]:
        """Update all records in ``self`` with the provided values.

        :param vals: fields to update and the value to set on them
        :raise AccessError: if the user may not modify these records/fields
        :raise ValidationError: on an invalid value for a selection field
        :raise UserError: if the operation would create a loop in an object
            hierarchy (e.g. setting an object as its own parent)

        * For numeric fields (:class:`~odoo.fields.Integer`,
          :class:`~odoo.fields.Float`) the value should be of the
          corresponding type
        * For :class:`~odoo.fields.Boolean`, the value should be a
          :class:`python:bool`
        * For :class:`~odoo.fields.Selection`, the value should match the
          selection values (generally :class:`python:str`, sometimes
          :class:`python:int`)
        * For :class:`~odoo.fields.Many2one`, the value should be the
          database identifier of the record to set
        * The expected value of a :class:`~odoo.fields.One2many` or
          :class:`~odoo.fields.Many2many` relational field is a list of
          :class:`~odoo.fields.Command` that manipulate the relation they
          implement. There are a total of 7 commands:
          :meth:`~odoo.fields.Command.create`,
          :meth:`~odoo.fields.Command.update`,
          :meth:`~odoo.fields.Command.delete`,
          :meth:`~odoo.fields.Command.unlink`,
          :meth:`~odoo.fields.Command.link`,
          :meth:`~odoo.fields.Command.clear`, and
          :meth:`~odoo.fields.Command.set`.
        * For :class:`~odoo.fields.Date` and `~odoo.fields.Datetime`,
          the value should be either a date(time), or a string.

          .. warning::

            If a string is provided for Date(time) fields,
            it must be UTC-only and formatted according to
            :const:`odoo.tools.misc.DEFAULT_SERVER_DATE_FORMAT` and
            :const:`odoo.tools.misc.DEFAULT_SERVER_DATETIME_FORMAT`

        * Other non-relational fields use a string for value

        .. note:: **Deferred SQL.** Unlike :meth:`create`/:meth:`unlink`,
            ``write()`` only updates the cache and marks fields dirty; the
            ``UPDATE`` is deferred to :meth:`flush_all` (or an implicit flush
            from ``search``/``read``/commit), batching writes into one
            ``UPDATE FROM VALUES``. So a raw SQL ``SELECT`` right after
            ``write()`` may see OLD values — read via the ORM, or
            ``flush_model()`` first.
        """
        if not self:
            return True

        prof = _OrmProfile(_orm_crud)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("write", self._name, len(self), frozenset(vals))

        self.check_access("write")
        for field_name in vals:
            try:
                self._check_field_access(self._fields[field_name], "write")
            except KeyError as e:
                raise ValueError(
                    f"Invalid field {field_name!r} in {self._name!r}"
                ) from e
        prof.mark("acl")
        env = self.env

        # set magic fields
        bad_names = bad_field_names(self)
        vals = {key: val for key, val in vals.items() if key not in bad_names}
        if self._log_access:
            vals.setdefault("write_uid", self.env.uid)
            vals.setdefault("write_date", self.env.cr.now())

        field_values = []  # [(field, value)]
        determine_inverses = defaultdict(list)  # {inverse: fields}
        fnames_modifying_relations = []
        protected = set()
        x2m_inverse_fnames = []
        for fname, value in vals.items():
            field = self._fields.get(fname)
            if not field:
                raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")
            field_values.append((field, value))
            if field.inverse:
                if field.type in ("one2many", "many2many"):
                    x2m_inverse_fnames.append(fname)
                determine_inverses[field.inverse].append(field)
            if self.pool.is_modifying_relations(field):
                fnames_modifying_relations.append(fname)
            if field.inverse or (field.compute and not field.readonly):
                if field.store or field.type not in ("one2many", "many2many"):
                    # Protect the field from recomputation while it is being
                    # inversed. For non-stored x2many fields, the value may hold
                    # new records (from command 0) needed for inversing but that
                    # should not survive a later recompute; not protecting the
                    # field invalidates it from cache, forcing recomputation once
                    # dependencies are up-to-date.
                    protected.update(self.pool.field_computed.get(field, [field]))

        # Pre-read all x2many inverse fields in one batch. They use command-
        # based writes (add/remove/update), so their current value must be in
        # cache before the field is protected from recomputation. fetch() (vs
        # self[fname] per field) populates all records at once without
        # triggering ensure_one() — but unlike the per-field read it neither
        # runs pending recomputes (a stored computed x2many pending from an
        # earlier write would be silently discarded: fetch caches the stale DB
        # relation, then mark_dirty's remove_to_compute drops the pending
        # computation without running it) nor populates non-stored fields
        # (whose baseline must be computed now, before this write's other
        # fields are marked dirty).  Handle both explicitly.
        if x2m_inverse_fnames:
            self._recompute_recordset(x2m_inverse_fnames)
            self.fetch(x2m_inverse_fnames)
            for fname in x2m_inverse_fnames:
                field = self._fields[fname]
                if not field.store:
                    # Union __get__ computes the whole recordset in one batch.
                    field.__get__(self)

        # force the computation of fields that are computed with some assigned
        # fields, but are not assigned themselves
        if protected:
            to_compute = [
                field.name
                for field in protected
                if field.compute and field.name not in vals
            ]
            if to_compute:
                self._recompute_recordset(to_compute)
        prof.mark("classify")

        # protect fields being written against recomputation
        with env.protecting(protected, self):
            # Modifying a relational field changes the "data path" between a
            # computed field and its dependency, so dependents must be recomputed
            # for both the OLD and NEW values (hence two modified() calls; only
            # needed for relational fields). E.g. moving a line from SO1 to SO2
            # (line.order_id = so2) must recompute the total amount on both
            # orders.
            if fnames_modifying_relations:
                self._modified_before(fnames_modifying_relations)
            prof.mark("before")

            # Fast path: singleton with a real ID — skip filtered("id") overhead
            _ids = self._ids
            if len(_ids) == 1 and _ids[0]:
                real_recs = self
            else:
                real_recs = self.filtered("id")

            # Process fields in write_sequence order (see Field.write_sequence):
            # 0=scalars/M2O → 10=monetary/properties → 20=x2many
            if len(field_values) > 1:
                field_values.sort(key=lambda item: item[0].write_sequence)
            for field, value in field_values:
                field.mark_dirty(self, value)
            prof.mark("dirty")

            # Call modified() after mark_dirty: it may trigger a search ->
            # flush -> recompute that would compute a field before its
            # dependencies are written. E.g. writing res.partner.name recomputes
            # display_name, which searches child_ids and flushes display_name
            # (it is in _order) before parent_id is written, computing too early.
            # (`test_01_website_reset_password_tour`)
            self.modified(vals)
            prof.mark("after")

            if self._parent_store and self._parent_name in vals:
                self.flush_model([self._parent_name])

            # Two-pass validation: pass 1 validates written fields excluding
            # inversed (their values are already in the dirty cache); inverses
            # run between the passes (they write to related models); pass 2
            # validates inversed fields. (create() runs inverses before both
            # passes since constraints may need the related records to exist.)
            inverse_fields = [f.name for fs in determine_inverses.values() for f in fs]
            real_recs._validate_fields(vals, inverse_fields)
            prof.mark("validate1")

            for fields in determine_inverses.values():
                # write again on non-stored fields that have been invalidated from cache
                for field in fields:
                    if (
                        not field.store
                        and (
                            not field.inherited
                            or field.type not in ("one2many", "many2many")
                        )
                        and any(field._cache_missing_ids(real_recs))
                    ):
                        field.mark_dirty(real_recs, vals[field.name])

                # inverse records that are not being computed
                try:
                    fields[0].determine_inverse(real_recs)
                except AccessError as e:
                    if fields[0].inherited:
                        description = self.env["ir.model"]._get(self._name).name
                        raise AccessError(
                            _(
                                "%(previous_message)s\n\nImplicitly accessed through '%(document_kind)s' (%(document_model)s).",
                                previous_message=e.args[0],
                                document_kind=description,
                                document_model=self._name,
                            )
                        ) from e
                    raise

            # Pass 2: validate constraints touching inversed fields.
            real_recs._validate_fields(inverse_fields)

        if self._check_company_auto:
            self._check_company(list(vals))

        prof.stop()
        if prof.debug:
            _fnames = (
                ", ".join(sorted(vals)) if len(vals) <= 20 else f"{len(vals)} fields"
            )
            _orm_crud.debug(
                "[%.3f ms] write %s: %d records, %s"
                " | acl=%.1f classify=%.1f before=%.1f dirty=%.1f after=%.1f"
                " validate=%.1f inverse=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(self),
                _fnames,
                prof.ms("start", "acl"),
                prof.ms("acl", "classify"),
                prof.ms("classify", "before"),
                prof.ms("before", "dirty"),
                prof.ms("dirty", "after"),
                prof.ms("after", "validate1"),
                prof.ms("validate1", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_write(self._name, len(self), prof.elapsed)

        return True

    def _write_multi(self, vals_list: list[ValuesType]) -> None:
        """Persist ``vals_list`` (one dict per record in ``self``) via batched
        UPDATEs.

        Driven by the cache flush (``CacheMixin._flush``), which builds a fresh
        dict per id; rows are grouped by their field-name set so each distinct
        set of columns becomes a single batched UPDATE.
        """
        # raise (not assert): under python -O a length mismatch would zip-
        # truncate rows and persist wrong values on the trailing records.
        if len(self) != len(vals_list):
            raise ValueError(
                f"_write_multi: len(records)={len(self)} != "
                f"len(vals_list)={len(vals_list)}"
            )

        if not self:
            return

        prof = _OrmProfile(_orm_crud)

        # determine records that require updating parent_path
        parent_records = (
            self._parent_store_update_prepare(vals_list) if self._parent_store else None
        )

        # Group rows by their (sorted) field-name set (see docstring). Aliased
        # inputs like [a, b, a] stay correct because the zip below pairs each id
        # with its own vals.
        # Pipeline batches multiple UPDATE statements in a single round-trip;
        # nesting is safe — psycopg3 reuses the active pipeline as a no-op.
        with self.env.cr.pipeline():
            if self._log_access:
                log_vals = {
                    "write_uid": self.env.uid,
                    "write_date": self.env.cr.now(),
                }
                vals_list = [(log_vals | vals) for vals in vals_list]
            updates = defaultdict(list)
            for id_, vals in zip(self._ids, vals_list, strict=True):
                if not vals:
                    # Nothing to write for this record (e.g. every dirty field
                    # flushed as PENDING on a _log_access=False model, so no
                    # write_uid/write_date merge padded it). An empty dict would
                    # crash `zip(*sorted(vals.items()))` on unpack; skip it.
                    continue
                fnames, row = zip(*sorted(vals.items()), strict=False)
                updates[fnames].append((id_,) + row)
            for fnames, rows in updates.items():
                for sub_rows in batched(rows, UPDATE_BATCH_SIZE, strict=False):
                    self._execute_update(fnames, sub_rows)

        # update parent_path
        if parent_records:
            parent_records._parent_store_update()

        if prof.debug:
            prof.stop()
            _orm_crud.debug(
                "[%.3f ms] _write_multi %s: %d records, %d column-group(s)",
                prof.elapsed * 1000,
                self._name,
                len(self),
                len(updates),
            )

    def _execute_update(self, fnames: tuple[str, ...], rows: list[tuple]) -> None:
        """Execute UPDATE FROM VALUES for a group of records sharing the same fields.

        :param fnames: Tuple of field names being updated (sorted).
        :param rows: List of tuples (id, val1, val2, ...) — one per record.
        """
        # Backend dispatch: in-memory backend or PostgreSQL (None = SQL).
        if (backend := self.env.backend) is not None:
            backend.update_rows(self, fnames, rows)
            return

        columns = []
        assignments = []
        for fname in fnames:
            field = self._fields[fname]
            # raise (not assert): under python -O a non-column field would build
            # a malformed UPDATE failing later with an opaque column_type error.
            # (``is_column`` implies ``column_type`` is truthy, so the second
            # branch never fires; it only narrows ``tuple[str, str] | None``.)
            column_type = field.column_type
            if not field.is_column or column_type is None:
                raise RuntimeError(
                    f"_execute_update: {field} is not a stored column field"
                )
            column = SQL.identifier(fname)
            # the type cast is necessary for some values, like NULLs
            expr = SQL('"__tmp".%s::%s', column, SQL(column_type[1]))
            if field.translate is True:
                # this is the SQL equivalent of:
                # None if expr is None else (
                #     (column or {'en_US': next(iter(expr.values()))}) | expr
                # )
                expr = SQL(
                    """CASE WHEN %(expr)s IS NULL THEN NULL ELSE
                        COALESCE(%(table)s.%(column)s, jsonb_build_object(
                            'en_US', jsonb_path_query_first(%(expr)s, '$.*')
                        )) || %(expr)s
                    END""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                )
            if field.company_dependent:
                fallbacks = self.env["ir.default"]._get_field_column_fallbacks(
                    self._name, fname
                )
                expr = SQL(
                    """(SELECT jsonb_object_agg(d.key, d.value)
                    FROM jsonb_each(COALESCE(%(table)s.%(column)s, '{}'::jsonb) || %(expr)s) d
                    JOIN jsonb_each(%(fallbacks)s) f
                    ON d.key = f.key AND d.value != f.value)""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                    fallbacks=fallbacks,
                )
            columns.append(column)
            assignments.append(SQL("%s = %s", column, expr))

        self.env.cr.execute(
            SQL(
                """ UPDATE %(table)s
                SET %(assignments)s
                FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                WHERE %(table)s."id" = "__tmp"."id"
            """,
                table=SQL.identifier(self._table),
                assignments=SQL(", ").join(assignments),
                values=SQL(", ").join(rows),
                columns=SQL(", ").join(columns),
            )
        )

    def _parent_store_update_prepare(self, vals_list: list[ValuesType]) -> Self:
        """Return the records in ``self`` that must update their parent_path
        field. This must be called before updating the parent field.
        """
        if not self._parent_store:
            return self.browse()
        # Backends without hierarchy support skip parent_path maintenance.
        backend = self.env.backend
        if backend is not None and not backend.supports_parent_store:
            return self.browse()

        # associate each new parent_id to its corresponding record ids
        parent_to_ids = defaultdict(list)
        for id_, vals in zip(self._ids, vals_list, strict=True):
            if self._parent_name in vals:
                parent_to_ids[vals[self._parent_name]].append(id_)

        if not parent_to_ids:
            return self.browse()

        self.flush_recordset([self._parent_name])

        # return the records for which the parent field will change
        sql_parent = SQL.identifier(self._parent_name)
        conditions = []
        for parent_id, ids in parent_to_ids.items():
            if parent_id:
                condition = SQL(
                    "(%s != %s OR %s IS NULL)",
                    sql_parent,
                    parent_id,
                    sql_parent,
                )
            else:
                condition = SQL("%s IS NOT NULL", sql_parent)
            conditions.append(SQL('("id" = ANY(%s) AND %s)', list(ids), condition))

        rows = self.env.execute_query(
            SQL(
                "SELECT id FROM %s WHERE %s ORDER BY id",
                SQL.identifier(self._table),
                SQL(" OR ").join(conditions),
            )
        )
        return self.browse(row[0] for row in rows)

    def _parent_store_update(self) -> None:
        """Update the parent_path field of ``self``."""
        for parent, records in self.grouped(self._parent_name).items():
            # determine new prefix of parent_path of records
            prefix = parent.parent_path or ""

            # check for recursion
            if prefix:
                parent_ids = {int(label) for label in prefix.split("/")[:-1]}
                if not parent_ids.isdisjoint(records._ids):
                    raise UserError(_("Recursion Detected."))

            # update parent_path of all records and their descendants
            updated = dict(
                self.env.execute_query(
                    SQL(
                        """ UPDATE %(table)s child
                    SET parent_path = concat(%(prefix)s::text, substr(child.parent_path,
                            length(node.parent_path) - length(node.id || '/') + 1))
                    FROM %(table)s node
                    WHERE node.id IN %(ids)s
                    AND child.parent_path LIKE concat(node.parent_path, %(wildcard)s::text)
                    RETURNING child.id, child.parent_path """,
                        table=SQL.identifier(self._table),
                        prefix=prefix,
                        ids=tuple(records.ids),
                        wildcard="%",
                    )
                )
            )

            # update the cache of updated nodes, and determine what to recompute
            field = self._fields["parent_path"]
            for id_, path in updated.items():
                field._update_cache(self.browse(id_), path)
            records = self.browse(updated)
            records.modified(["parent_path"])
