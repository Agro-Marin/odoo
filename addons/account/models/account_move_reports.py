from odoo import _, fields, models

from ..tools import debug_log as dbg


class AccountMove(models.Model):
    _inherit = "account.move"

    closing_return_id = fields.Many2one(
        comodel_name="account.return", index="btree_not_null", copy=False
    )

    @dbg.timed
    def action_view_tax_return(self):
        dbg.lifecycle.debug("action_view_tax_return on %s", dbg.rec(self))
        return {
            "type": "ir.actions.act_window",
            "name": self.closing_return_id.name,
            "res_model": "account.return.check",
            "view_mode": "kanban",
            "context": {
                "active_model": "account.return",
                "active_id": self.closing_return_id.id,
                "active_ids": self.closing_return_id.ids,
                "account_return_view_id": self.env.ref(
                    "account.account_return_kanban_view"
                ).id,
            },
            "domain": [["return_id", "=", self.closing_return_id.id]],
            "views": [
                (
                    self.env.ref("account.account_return_check_kanban_view").id,
                    "kanban",
                )
            ],
        }

    @dbg.timed
    def unlink(self):
        dbg.lifecycle.debug("unlink %s", dbg.rec(self))
        for move in self:
            if move.closing_return_id:
                if len(move.closing_return_id.company_ids) == 1:
                    move.closing_return_id.message_post(
                        body=_("Closing entry deleted"),
                        message_type="comment",
                    )
                else:
                    move.closing_return_id.message_post(
                        body=_(
                            "Closing entry deleted for company %s",
                            move.closing_return_id.company_id,
                        ),
                        message_type="comment",
                    )
        return super().unlink()

    @dbg.timed
    def _post_entries(self):
        dbg.lifecycle.debug("_post_entries on %s", dbg.rec(self))
        posted_moves = super()._post_entries()
        posted_moves._update_accounts_audit_status()
        return posted_moves

    @dbg.timed
    def action_draft(self):
        dbg.lifecycle.debug("action_draft on %s", dbg.rec(self))
        posted_moves = self.filtered(lambda move: move.state == "posted")
        res = super().action_draft()
        posted_moves._update_accounts_audit_status()
        return res

    @dbg.timed
    def _update_accounts_audit_status(self):
        if not self:
            return

        all_statuses = (
            self.env["account.audit.account.status"]
            .sudo()
            .search(
                [
                    ("account_id", "in", self.line_ids.account_id.ids),
                    ("status", "in", (False, "reviewed", "supervised")),
                    ("audit_id.company_ids", "in", self.company_id.ids),
                ]
            )
        )

        if not all_statuses:
            return

        account_to_statuses = all_statuses.grouped("account_id")
        audits = all_statuses.mapped("audit_id")
        audit_id_to_dates = {
            audit.id: {"date_from": audit.date_from, "date_to": audit.date_to}
            for audit in audits
        }

        statuses_to_update = self.env["account.audit.account.status"]
        empty_status = self.env["account.audit.account.status"]

        for line in self.line_ids:
            matching_statuses = account_to_statuses.get(
                line.account_id, empty_status
            ).filtered(
                lambda status, line=line: (
                    audit_id_to_dates[status.audit_id.id]["date_from"]
                    <= line.date
                    <= audit_id_to_dates[status.audit_id.id]["date_to"]
                )
            )
            statuses_to_update |= matching_statuses

        if statuses_to_update:
            statuses_to_update.status = "todo"
