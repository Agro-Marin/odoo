import typing
from itertools import batched
from typing import Self

from odoo.exceptions import UserError
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads
from odoo.libs.profiling import _n1_enabled, _OrmProfile
from odoo.tools import SQL
from odoo.tools.translate import _

from ...primitives import MODULE_UNINSTALL_FLAG
from ._crud_common import (
    _orm_crud,
    _unlink,
)
from ._model_stubs import _ModelStubs

_UNLINK_LOG_MAX_IDS = 1000
"""Ids logged verbatim by :meth:`UnlinkMixin.unlink` before it summarizes."""


class UnlinkMixin(_ModelStubs):
    __slots__ = ()

    def unlink(self) -> typing.Literal[True]:
        if not self:
            return True

        prof = _OrmProfile(_orm_crud)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("unlink", self._name, len(self), frozenset())

        self.check_access("unlink")
        prof.mark("acl")

        for func in self._ondelete_methods:
            if func._ondelete or not self.env.context.get(MODULE_UNINSTALL_FLAG):
                func(self)
        prof.mark("ondelete")

        self.env.flush_all()

        core = self.env._core
        if core.has_pending():
            model_name = self._name
            deleted_ids = self._ids
            for field in list(core.pending_fields()):
                if field.model_name == model_name:
                    core.mark_done(field, deleted_ids)

        prof.mark("flush")

        cr = self.env.cr
        Data = self.env["ir.model.data"].sudo().with_context({})
        Defaults = self.env["ir.default"].sudo()
        Attachment = self.env["ir.attachment"].sudo()
        ir_model_data_unlink = Data
        ir_attachment_unlink = Attachment

        with self.env.protecting(self._fields.values(), self):
            self._modified_before(self._fields)
        prof.mark("before")

        deleted_ids = self.ids
        for sub_ids in batched(deleted_ids, cr.BATCH_SIZE, strict=False):
            data, attachments = self._unlink_process_batch(
                sub_ids,
                Data,
                Defaults,
                Attachment,
            )
            ir_model_data_unlink |= data
            ir_attachment_unlink |= attachments
        prof.mark("sql")

        if self.env.context.get(MODULE_UNINSTALL_FLAG):
            self.env.invalidate_all(flush=False)
        else:
            self._invalidate_after_delete()

        if ir_model_data_unlink:
            ir_model_data_unlink.unlink()
        if ir_attachment_unlink:
            ir_attachment_unlink.unlink()

        self._log_unlinked_ids(deleted_ids)

        prof.stop()
        self._log_unlink_profile(prof, len(deleted_ids))

        return True

    def _log_unlinked_ids(self, deleted_ids: list[int]) -> None:
        if len(deleted_ids) <= _UNLINK_LOG_MAX_IDS:
            _unlink.info(
                "User #%s deleted %s records with IDs: %r",
                self.env.uid,
                self._name,
                deleted_ids,
            )
        else:
            _unlink.info(
                "User #%s deleted %s records: %d IDs in [%s..%s], first %d: %r",
                self.env.uid,
                self._name,
                len(deleted_ids),
                min(deleted_ids),
                max(deleted_ids),
                _UNLINK_LOG_MAX_IDS,
                deleted_ids[:_UNLINK_LOG_MAX_IDS],
            )

    def _log_unlink_profile(self, prof: _OrmProfile, record_count: int) -> None:
        if prof.debug:
            _orm_crud.debug(
                "[%.3f ms] unlink %s: %d records"
                " | acl=%.1f ondelete=%.1f flush=%.1f before=%.1f"
                " sql=%.1f invalidate=%.1f",
                prof.elapsed * 1000,
                self._name,
                record_count,
                prof.ms("start", "acl"),
                prof.ms("acl", "ondelete"),
                prof.ms("ondelete", "flush"),
                prof.ms("flush", "before"),
                prof.ms("before", "sql"),
                prof.ms("sql", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_unlink(self._name, record_count, prof.elapsed)

    def _invalidate_after_delete(self) -> None:
        env = self.env
        registry = env.registry
        cascades = registry.models_cascading_from
        gone = {self._name}
        todo = [self._name]
        while todo:
            for model_name in cascades.get(todo.pop(), ()):
                if model_name not in gone:
                    gone.add(model_name)
                    todo.append(model_name)
        fields_by_comodel = registry.fields_by_comodel
        for model_name in gone:
            for field in env[model_name]._fields.values():
                field._invalidate_cache(env, keep_dirty=True)
            for field in fields_by_comodel.get(model_name, ()):
                field._invalidate_cache(env, keep_dirty=True)

    def _unlink_process_batch(
        self,
        sub_ids: tuple[int, ...],
        Data: typing.Any,
        Defaults: typing.Any,
        Attachment: typing.Any,
    ) -> tuple[Self, Self]:
        return self.env.backend.delete(self, sub_ids, Data, Defaults, Attachment)

    def _delete_sql(
        self,
        sub_ids: tuple[int, ...],
        Data: typing.Any,
        Defaults: typing.Any,
        Attachment: typing.Any,
    ) -> tuple[Self, Self]:
        cr = self.env.cr
        records = self.browse(sub_ids)

        cr.execute(
            SQL(
                "DELETE FROM %s WHERE id = ANY(%s)",
                SQL.identifier(self._table),
                list(sub_ids),
            )
        )

        data = Data.search([("model", "=", self._name), ("res_id", "in", sub_ids)])

        cr.execute(
            SQL(
                "SELECT id FROM ir_attachment WHERE res_model=%s AND res_id = ANY(%s)",
                self._name,
                list(sub_ids),
            )
        )
        attachments = Attachment.browse(row[0] for row in cr.fetchall())

        if (
            many2one_fields := self.env.registry.many2one_company_dependents[self._name]
        ) and not self.env.context.get(MODULE_UNINSTALL_FLAG):
            IrModelFields = self.env["ir.model.fields"]
            field_ids = tuple(
                IrModelFields._get_ids(field.model_name).get(field.name)
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
                field = self.env[ir_field.model]._fields[ir_field.name]
                record = self.browse(json_loads(default.json_value))
                raise UserError(
                    _(
                        "Unable to delete %(record)s because it is used as the default value of %(field)s",
                        record=record,
                        field=field,
                    )
                )

        if many2one_fields and not all(
            isinstance(id_, int) and id_ > 0 for id_ in sub_ids
        ):
            raise TypeError(
                f"_unlink_process_batch: sub_ids must be positive ints, got {sub_ids!r}"
            )
        for field in many2one_fields:
            model = self.env[field.model_name]
            if field.ondelete == "restrict" and not self.env.context.get(
                MODULE_UNINSTALL_FLAG
            ):
                if res := self.env.execute_query(
                    SQL(
                        """
                    SELECT id, %(field)s
                    FROM %(table)s
                    WHERE %(field)s IS NOT NULL
                    AND %(field)s @? %(jsonpath)s
                    ORDER BY id
                    LIMIT 1
                    """,
                        table=SQL.identifier(model._table),
                        field=SQL.identifier(field.name),
                        jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                    )
                ):
                    on_restrict_id, field_json = res[0]
                    to_delete_id = next(iter(field_json.values()))
                    on_restrict_record = model.browse(on_restrict_id)
                    to_delete_record = self.browse(to_delete_id)
                    raise UserError(
                        _(
                            "You cannot delete %(to_delete_record)s, as it is used by %(on_restrict_record)s",
                            to_delete_record=to_delete_record,
                            on_restrict_record=on_restrict_record,
                        )
                    )
            else:
                affected = self.env.execute_query(
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
                        table=SQL.identifier(model._table),
                        field=SQL.identifier(field.name),
                        ids=sub_ids,
                        jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                    )
                )
                if affected:
                    affected_recs = model.browse(row[0] for row in affected)
                    affected_recs.modified([field.name])

        Defaults.discard_records(records)

        return data, attachments
