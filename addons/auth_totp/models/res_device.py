from odoo import api, fields, models
from odoo.db.schema import add_foreign_key, column_exists, table_exists
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL

from odoo.addons.base.models.res_device import _current_key_hash

_debug = DebugLog(__name__)


def ensure_trust_foreign_key(cr) -> None:
    # the ORM links no foreign key to auth_totp.device, a hand-made table, and
    # its expired keys are deleted in SQL: only the database clears the link
    if not (
        table_exists(cr, "auth_totp_device")
        and column_exists(cr, "res_device", "totp_device_id")
    ):
        return
    cr.execute(
        SQL(
            """
            SELECT 1 FROM pg_constraint
            WHERE contype = 'f'
              AND conrelid = 'res_device'::regclass
              AND confrelid = 'auth_totp_device'::regclass
            """
        )
    )
    if not cr.rowcount:
        add_foreign_key(
            cr, "res_device", "totp_device_id", "auth_totp_device", "id", "SET NULL"
        )
        _debug.lifecycle("trust_foreign_key_added")


class ResDevice(models.Model):
    _inherit = "res.device"

    totp_device_id = fields.Many2one(
        comodel_name="auth_totp.device",
        string="Trusted for 2FA",
        copy=False,
        readonly=True,
    )

    def init(self) -> None:
        super().init()
        ensure_trust_foreign_key(self.env.cr)

    @api.model
    def _trust_current_device(self, trust_id: int) -> None:
        self.flush_model(["totp_device_id"])
        self.env.cr.execute(
            SQL(
                "UPDATE res_device SET totp_device_id = %s "
                "WHERE user_id = %s AND key_hash = %s",
                trust_id,
                self.env.uid,
                _current_key_hash(),
            )
        )
        linked = self.env.cr.rowcount
        self.invalidate_model(["totp_device_id"])
        _debug.lifecycle("device_trusted", uid=self.env.uid, linked=linked)

    def _revoke(self) -> bool:
        trusts = self.totp_device_id
        logout = super()._revoke()
        if trusts:
            trusts._remove()
            _debug.lifecycle("device_trust_removed", trusts=trusts.ids)
        return logout
