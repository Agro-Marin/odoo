"""Record deletion: ``unlink`` and its batch helper.

Split out of the former CrudMixin; see _crud_common.py for shared
constants. Copy/duplication lives in copy.py (CopyMixin).
"""

import typing
from itertools import batched
from typing import Self

from odoo.exceptions import UserError
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads
from odoo.tools import SQL
from odoo.tools.nplusone import _n1_enabled
from odoo.tools.orm_profiler import _OrmProfile
from odoo.tools.translate import _

from ._crud_common import (
    _orm_crud,
    _unlink,
)
from ._model_stubs import _ModelStubs


class UnlinkMixin(_ModelStubs):
    """Record deletion: ``unlink`` and its batch helper."""

    __slots__ = ()

    def unlink(self) -> typing.Literal[True]:
        """Delete the records in ``self``.

        :raise AccessError: if the user may not delete all the given records
        :raise UserError: if a record is the default property of other records
        """
        if not self:
            return True

        prof = _OrmProfile(_orm_crud)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("unlink", self._name, len(self), frozenset())

        self.check_access("unlink")
        prof.mark("acl")

        from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG

        for func in self._ondelete_methods:
            # func._ondelete is True if it should be called during uninstallation
            if func._ondelete or not self.env.context.get(MODULE_UNINSTALL_FLAG):
                func(self)
        prof.mark("ondelete")

        # TOFIX: avoids an infinite loop where recomputing a field triggers
        # recompute of another field sharing the same compute function, which
        # re-triggers both.
        core = self.env._core
        if core.has_pending():
            # Iterate pending entries (typically few) rather than all model
            # fields (often 100+); clear only entries for the current model.
            model_name = self._name
            deleted_ids = self._ids
            for field in list(core.pending_fields()):
                if field.model_name == model_name:
                    core.mark_done(field, deleted_ids)

        self.env.flush_all()

        prof.mark("flush")

        cr = self.env.cr
        Data = self.env["ir.model.data"].sudo().with_context({})
        Defaults = self.env["ir.default"].sudo()
        Attachment = self.env["ir.attachment"].sudo()
        ir_model_data_unlink = Data
        ir_attachment_unlink = Attachment

        # Capture ALL dependency paths before deletion (see _modified_before
        # docstring for why unlink passes ALL fields, not just relational ones).
        # Example: deleting a sale order line recomputes the order's total amount.
        with self.env.protecting(self._fields.values(), self):
            self._modified_before(self._fields)
        prof.mark("before")

        for sub_ids in batched(self.ids, cr.BATCH_SIZE, strict=False):
            data, attachments = self._unlink_process_batch(
                sub_ids,
                Data,
                Defaults,
                Attachment,
            )
            ir_model_data_unlink |= data
            ir_attachment_unlink |= attachments
        prof.mark("sql")

        # Invalidate the *whole* cache: the ORM doesn't track all DB-side
        # changes (e.g. cascading deletes), and targeted invalidation misses
        # non-stored computed/related fields reached through multi-hop FK chains.
        self.env.invalidate_all(flush=False)

        if ir_model_data_unlink:
            ir_model_data_unlink.unlink()
        if ir_attachment_unlink:
            ir_attachment_unlink.unlink()

        # auditing: deletions are infrequent and leave no trace in the database
        _unlink.info(
            "User #%s deleted %s records with IDs: %r",
            self.env.uid,
            self._name,
            self.ids,
        )

        prof.stop()
        if prof.debug:
            _orm_crud.debug(
                "[%.3f ms] unlink %s: %d records"
                " | acl=%.1f ondelete=%.1f flush=%.1f before=%.1f"
                " sql=%.1f invalidate=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(self),
                prof.ms("start", "acl"),
                prof.ms("acl", "ondelete"),
                prof.ms("ondelete", "flush"),
                prof.ms("flush", "before"),
                prof.ms("before", "sql"),
                prof.ms("sql", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_unlink(self._name, len(self), prof.elapsed)

        return True

    def _unlink_process_batch(
        self,
        sub_ids: tuple[int, ...],
        Data: typing.Any,
        Defaults: typing.Any,
        Attachment: typing.Any,
    ) -> tuple[Self, Self]:
        """Process one batch of record deletions during unlink().

        Executes DELETE SQL, collects ir.model.data and ir.attachment records
        for cleanup, handles company-dependent M2O restrict/set-null cascade,
        and discards ir.default entries.

        :param sub_ids: tuple of record IDs to delete in this batch
        :param Data: ir.model.data model proxy (sudo, empty context)
        :param Defaults: ir.default model proxy (sudo)
        :param Attachment: ir.attachment model proxy (sudo)
        :return: (data_records, attachment_records) to unlink after all batches
        """
        # Backend dispatch: in-memory backend or PostgreSQL (None = SQL).
        if (backend := self.env.backend) is not None:
            return backend.delete(self, sub_ids, Data, Attachment)

        from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG

        cr = self.env.cr
        records = self.browse(sub_ids)

        cr.execute(
            SQL(
                "DELETE FROM %s WHERE id = ANY(%s)",
                SQL.identifier(self._table),
                list(sub_ids),
            )
        )

        # Remove the ir_model_data reference for xml/csv-created records:
        # they have no real FK, so the reference would dangle. Done as
        # superuser and with no context to avoid access restrictions and
        # side-effects during admin calls.
        data = Data.search([("model", "=", self._name), ("res_id", "in", sub_ids)])

        # Likewise remove the relevant ir_attachment records (via raw SQL:
        # ir_attachment's search() is overridden to hide attachments of
        # deleted records).
        cr.execute(
            SQL(
                "SELECT id FROM ir_attachment WHERE res_model=%s AND res_id = ANY(%s)",
                self._name,
                list(sub_ids),
            )
        )
        attachments = Attachment.browse(row[0] for row in cr.fetchall())

        # block deleting a record used as an ir.default fallback for a company-
        # dependent m2o, unless MODULE_UNINSTALL_FLAG (then discard_records below
        # clears the fallback)
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

        # on delete set null/restrict for jsonb company-dependent many2one.
        # Defensive: the JSONPath below interpolates each id via f-string
        # (psycopg can't bind parameters inside a jsonpath expression). Safe
        # because ``self.ids`` returns only ints; reject anything else loudly so
        # a future caller can't smuggle a SQL fragment through ``sub_ids``.
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
                # Set null on company-dependent M2O references.
                # RETURNING id lets us trigger modified() on affected
                # records so their computed dependents get recomputed.
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

        # For the same reason, remove the defaults having some of the
        # records as value
        Defaults.discard_records(records)

        return data, attachments
