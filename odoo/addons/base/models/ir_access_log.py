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
    ("privilege_used", "Privilege used"),
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
    model_name = fields.Char(
        string="Model",
        readonly=True,
    )
    operation = fields.Char(readonly=True)
    res_ids = fields.Char(
        string="Records",
        readonly=True,
        help="The ids the operation touched, the first hundred.",
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

    @api.model
    def _record_privileged(self, model_name: str, operation: str, ids: tuple) -> None:
        # a create, write or delete made under a privilege, on a model that
        # declares _access_audit or under a privilege that asks for it
        privileges = self.env["res.groups"].sudo().browse(sorted(self.env.privileges))
        audited = self.env.registry[model_name]._access_audit
        privileges = privileges if audited else privileges.filtered("audit_privilege")
        if not privileges:
            return
        record_ids = [id_ for id_ in ids if isinstance(id_, int)]
        self._record(
            [
                {
                    "event": "privilege_used",
                    "subject_user_id": self.env.uid,
                    "group_id": privilege.id,
                    "model_name": model_name,
                    "operation": operation,
                    "res_ids": ",".join(map(str, record_ids[:100])),
                    "reason": self.env.context.get("privilege_reason") or False,
                }
                for privilege in privileges
            ]
        )

    def write(self, vals: dict[str, Any]) -> bool:
        if not self:
            return True
        raise UserError(self.env._("The authorization log cannot be changed."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_by_the_superuser(self) -> None:
        if not self.env.su:
            raise UserError(self.env._("The authorization log cannot be deleted."))
