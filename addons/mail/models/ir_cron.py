import typing

from odoo import SUPERUSER_ID, fields, models
from odoo.libs.debug_log import DebugLog

if typing.TYPE_CHECKING:
    from odoo.addons.bus.models.res_users import ResUsers

_debug = DebugLog(__name__)


class IrCron(models.AbstractModel):
    _name = "ir.cron"
    _inherit = ["ir.cron", "mixin.mail.thread", "mixin.mail.activity"]

    user_id: ResUsers = fields.Many2one(tracking=True)
    repeat_interval = fields.Integer(tracking=True)
    repeat_unit = fields.Selection(tracking=True)
    priority = fields.Integer(tracking=True)

    def _notify_admin(self, message: str) -> None:
        channel_admin = self.env.ref("mail.channel_admin", raise_if_not_found=False)
        _debug.lifecycle(
            "admin_notified", channel=channel_admin.id if channel_admin else None
        )
        if channel_admin:
            channel_admin.with_user(SUPERUSER_ID).message_post(body=message)
        super()._notify_admin(message)
