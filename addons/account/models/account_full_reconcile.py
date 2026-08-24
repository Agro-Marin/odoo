from odoo import Command, api, fields, models


class AccountFullReconcile(models.Model):
    _name = "account.full.reconcile"
    _description = "Full Reconcile"

    partial_reconcile_ids = fields.One2many(
        "account.partial.reconcile",
        "full_reconcile_id",
        string="Reconciliation Parts",
    )
    reconciled_line_ids = fields.One2many(
        "account.move.line",
        "full_reconcile_id",
        string="Matched Journal Items",
    )

    @api.model_create_multi
    def create(self, vals_list):
        def get_ids(commands):
            for command in commands:
                if command[0] == Command.LINK:
                    yield command[1]
                elif command[0] == Command.SET:
                    yield from command[2]
                else:
                    raise ValueError("Unexpected command: %s" % command)

        move_line_ids = [
            list(get_ids(vals.pop("reconciled_line_ids"))) for vals in vals_list
        ]
        partial_ids = [
            list(get_ids(vals.pop("partial_reconcile_ids"))) for vals in vals_list
        ]
        fulls = super(
            AccountFullReconcile, self.with_context(tracking_disable=True)
        ).create(vals_list)

        self.env.cr.execute_values(
            """
            UPDATE account_move_line line
               SET full_reconcile_id = source.full_id
              FROM (VALUES %s) AS source(full_id, line_ids)
             WHERE line.id = ANY(source.line_ids)
        """,
            [
                (full.id, line_ids)
                for full, line_ids in zip(fulls, move_line_ids, strict=True)
            ],
            page_size=1000,
        )
        fulls.reconciled_line_ids.invalidate_recordset(
            ["full_reconcile_id"], flush=False
        )
        fulls.invalidate_recordset(["reconciled_line_ids"], flush=False)

        self.env.cr.execute_values(
            """
            UPDATE account_partial_reconcile partial
               SET full_reconcile_id = source.full_id
              FROM (VALUES %s) AS source(full_id, partial_ids)
             WHERE partial.id = ANY(source.partial_ids)
        """,
            [
                (full.id, line_ids)
                for full, line_ids in zip(fulls, partial_ids, strict=True)
            ],
            page_size=1000,
        )
        fulls.partial_reconcile_ids.invalidate_recordset(
            ["full_reconcile_id"], flush=False
        )
        fulls.invalidate_recordset(["partial_reconcile_ids"], flush=False)

        self.env["account.partial.reconcile"]._update_matching_number(
            fulls.reconciled_line_ids
        )
        return fulls

    def unlink(self):
        amls = self.reconciled_line_ids
        res = super().unlink()
        # The caller that is also removing partials recomputes over a superset of
        # these lines straight after; doing it here as well is one pass wasted.
        if self.env.context.get("defer_matching_number_update"):
            return res
        amls = amls.exists()
        if amls:
            self.env["account.partial.reconcile"]._update_matching_number(amls)
        return res
