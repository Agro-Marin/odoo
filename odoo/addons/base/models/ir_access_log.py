from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError

ACCESS_LOG_EVENTS = [
    ("grant_created", "Grant created"),
    ("grant_changed", "Grant changed"),
    ("grant_revoked", "Grant revoked"),
    ("grant_expired", "Grant expired"),
    ("grant_migrated", "Memberships migrated"),
]


class IrAccessLog(models.Model):
    _name = "ir.access.log"
    _description = "Authorization Log"
    _order = "id desc"
    _rec_name = "event"
    _allow_sudo_commands = False

    event = fields.Selection(
        selection=ACCESS_LOG_EVENTS,
        index=True,
        readonly=True,
        required=True,
    )
    actor_id = fields.Many2one(
        comodel_name="res.users",
        index=True,
        readonly=True,
        ondelete="set null",
        help="The user whose request made the change, also when the code that "
        "made it ran as the superuser.",
    )
    subject_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Subject",
        index=True,
        readonly=True,
        ondelete="set null",
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        index=True,
        readonly=True,
        ondelete="set null",
    )
    grant_id = fields.Many2one(
        comodel_name="res.users.grant",
        index=True,
        readonly=True,
        ondelete="set null",
    )
    cause = fields.Char(readonly=True)
    cause_model = fields.Char(readonly=True)
    cause_res_id = fields.Many2oneReference(
        model_field="cause_model",
        string="Cause Record",
        readonly=True,
    )
    reason = fields.Char(readonly=True)
    count = fields.Integer(
        readonly=True,
        help="How many grants one row stands for (a migration writes one row).",
    )

    @api.model
    def _record(self, vals_list: list[ValuesType]) -> Self:
        if not vals_list:
            return self.browse()
        actor = self.env.uid
        return self.sudo().create([{"actor_id": actor, **vals} for vals in vals_list])

    def write(self, vals: dict[str, Any]) -> bool:
        if not self:
            return True
        raise UserError(self.env._("The authorization log cannot be changed."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_by_the_superuser(self) -> None:
        if not self.env.su:
            raise UserError(self.env._("The authorization log cannot be deleted."))
