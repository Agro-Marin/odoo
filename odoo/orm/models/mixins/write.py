import typing
from collections import defaultdict
from typing import Self

from odoo.exceptions import AccessError, UserError
from odoo.libs.profiling import _n1_enabled, _OrmProfile
from odoo.libs.sql import SQL
from odoo.tools.translate import _

from ..._typing import ValuesType
from ._crud_common import (
    _orm_crud,
    bad_field_names,
)
from ._model_stubs import _ModelStubs


class _WriteFieldPlan(typing.NamedTuple):
    field_values: list
    determine_inverses: dict
    fnames_modifying_relations: list
    protected: set
    x2m_inverse_fnames: list


class WriteMixin(_ModelStubs):
    __slots__ = ()

    def _increment_fields_skiplock(self, *fields: str) -> bool:
        if not self:
            return False

        for field in fields:
            if not self._fields[field].is_integer:
                raise ValueError(
                    f"_increment_fields_skiplock: field {field!r} is not an integer"
                )

        cr = self.env.cr
        tablename = self._table
        cr.execute(
            SQL(
                """
            UPDATE %s
               SET %s
             WHERE id IN (SELECT id FROM %s WHERE id = ANY(%s) FOR UPDATE SKIP LOCKED)
            """,
                SQL.identifier(tablename),
                SQL(", ").join(
                    SQL(
                        "%s = COALESCE(%s, 0) + 1",
                        SQL.identifier(field),
                        SQL.identifier(field),
                    )
                    for field in fields
                ),
                SQL.identifier(tablename),
                self.ids,
            )
        )
        return bool(cr.rowcount)

    def _write_check_field_access(self, vals: ValuesType) -> None:
        self.check_access("write")
        for field_name in vals:
            try:
                self._check_field_access(self._fields[field_name], "write")
            except KeyError as e:
                raise ValueError(
                    f"Invalid field {field_name!r} in {self._name!r}"
                ) from e

    def _write_classify_fields(self, vals: ValuesType) -> _WriteFieldPlan:
        plan = _WriteFieldPlan([], defaultdict(list), [], set(), [])
        for fname, value in vals.items():
            field = self._fields[fname]
            plan.field_values.append((field, value))
            if field.inverse:
                if field.is_x2many:
                    plan.x2m_inverse_fnames.append(fname)
                plan.determine_inverses[field.inverse].append(field)
            if self.pool.is_modifying_relations(field):
                plan.fnames_modifying_relations.append(fname)
            if field.inverse or (field.compute and not field.readonly):
                if field.store or not field.is_x2many:
                    plan.protected.update(self.pool.field_computed.get(field, [field]))
        return plan

    def _write_settle_protected(self, plan: _WriteFieldPlan, vals: ValuesType) -> None:
        if plan.x2m_inverse_fnames:
            self._recompute_recordset(plan.x2m_inverse_fnames)
            self.fetch(plan.x2m_inverse_fnames)
            for fname in plan.x2m_inverse_fnames:
                field = self._fields[fname]
                if not field.store:
                    field.__get__(self)

        if plan.protected:
            to_compute = [
                field.name
                for field in plan.protected
                if field.compute and field.name not in vals
            ]
            if to_compute:
                self._recompute_recordset(to_compute)

    def _write_determine_inverses(
        self, determine_inverses: dict, real_recs: Self, vals: ValuesType
    ) -> None:
        for fields in determine_inverses.values():
            for field in fields:
                if (
                    not field.store
                    and (not field.inherited or not field.is_x2many)
                    and any(field._cache_missing_ids(real_recs))
                ):
                    field.mark_dirty(real_recs, vals[field.name])

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

    def write(self, vals: ValuesType) -> typing.Literal[True]:
        if not self:
            return True

        prof = _OrmProfile(_orm_crud)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("write", self._name, len(self), frozenset(vals))

        self._write_check_field_access(vals)
        prof.mark("acl")
        env = self.env

        bad_names = bad_field_names(self)
        vals = {key: val for key, val in vals.items() if key not in bad_names}
        if self._log_access:
            vals.setdefault("write_uid", self.env.uid)
            vals.setdefault("write_date", self.env.cr.now())

        plan = self._write_classify_fields(vals)
        field_values = plan.field_values
        determine_inverses = plan.determine_inverses
        protected = plan.protected
        self._write_settle_protected(plan, vals)
        prof.mark("classify")

        with env.protecting(protected, self):
            if plan.fnames_modifying_relations:
                self._modified_before(plan.fnames_modifying_relations)
            prof.mark("before")

            _ids = self._ids
            if len(_ids) == 1 and _ids[0]:
                real_recs = self
            else:
                real_recs = self.filtered("id")

            if len(field_values) > 1:
                field_values.sort(key=lambda item: item[0].write_sequence)
            for field, value in field_values:
                field.mark_dirty(self, value)
            prof.mark("dirty")

            self.modified(vals)
            prof.mark("after")

            if self._parent_store and self._parent_name in vals:
                self.flush_model([self._parent_name])

            inverse_fields = [f.name for fs in determine_inverses.values() for f in fs]
            real_recs._check_fields(vals, inverse_fields)
            prof.mark("validate")

            self._write_determine_inverses(determine_inverses, real_recs, vals)

            real_recs._check_fields(inverse_fields)

        if self._check_company_auto:
            self._check_company(list(vals))

        prof.stop("inverse")
        if prof.debug:
            _fnames = (
                ", ".join(sorted(vals)) if len(vals) <= 20 else f"{len(vals)} fields"
            )
            prof.report(
                _orm_crud, "write %s: %d records, %s", self._name, len(self), _fnames
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record("write", self._name, len(self), prof.elapsed)

        return True

    def _write_multi(self, vals_list: list[ValuesType]) -> None:
        if len(self) != len(vals_list):
            raise ValueError(
                f"_write_multi: len(records)={len(self)} != "
                f"len(vals_list)={len(vals_list)}"
            )

        if not self:
            return

        prof = _OrmProfile(_orm_crud)

        parent_records = (
            self._parent_store_update_prepare(vals_list) if self._parent_store else None
        )

        log_vals: ValuesType = (
            {"write_uid": self.env.uid, "write_date": self.env.cr.now()}
            if self._log_access
            else {}
        )
        log_only_ids: dict[str, list] = {fname: [] for fname in log_vals}

        with self.env.cr.pipeline():
            updates = defaultdict(list)
            for id_, vals in zip(self._ids, vals_list, strict=True):
                if not vals:
                    continue
                if log_vals:
                    for fname in log_vals:
                        if fname not in vals:
                            log_only_ids[fname].append(id_)
                    vals = log_vals | vals
                fnames, row = zip(*sorted(vals.items()), strict=False)
                updates[fnames].append((id_,) + row)
            for fnames, rows in updates.items():
                self._execute_update(fnames, rows)

        self._sync_log_access_cache(log_vals, log_only_ids)

        if parent_records:
            parent_records._parent_store_update()

        prof.stop()
        prof.report(
            _orm_crud,
            "_write_multi %s: %d records, %d column-group(s)",
            self._name,
            len(self),
            len(updates),
        )

    def _sync_log_access_cache(
        self, log_vals: ValuesType, log_only_ids: dict[str, list]
    ) -> None:
        for fname, ids in log_only_ids.items():
            if not ids:
                continue
            field = self._fields[fname]
            records = self.browse(ids)
            field._update_cache(
                records,
                field.convert_to_cache(log_vals[fname], records, validate=False),
            )

    def _execute_update(self, fnames: tuple[str, ...], rows: list[tuple]) -> None:
        self.env.backend.update_rows(self, fnames, rows)

    def _parent_store_update_prepare(self, vals_list: list[ValuesType]) -> Self:
        if not self._parent_store:
            return self.browse()
        if not self.env.backend.supports_parent_store:
            return self.browse()

        parent_to_ids = defaultdict(list)
        for id_, vals in zip(self._ids, vals_list, strict=True):
            if self._parent_name in vals:
                parent_to_ids[vals[self._parent_name]].append(id_)

        if not parent_to_ids:
            return self.browse()

        self.flush_recordset([self._parent_name])

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
        for parent, records in self.grouped(self._parent_name).items():
            prefix = parent.parent_path or ""

            if prefix:
                parent_ids = {int(label) for label in prefix.split("/")[:-1]}
                if not parent_ids.isdisjoint(records._ids):
                    raise UserError(_("Recursion Detected."))

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

            self._fields["parent_path"]._update_cache_items(self.env, updated.items())
            self.browse(updated).modified(["parent_path"])
