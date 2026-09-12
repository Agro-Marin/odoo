from odoo import api, models

from ..tools import debug_log as dbg


class MailTrackingValue(models.Model):
    _inherit = "mail.tracking.value"

    @api.ondelete(at_uninstall=True)
    @dbg.timed
    def _except_audit_log(self):
        dbg.lifecycle.debug("_except_audit_log on %s", dbg.rec(self))
        self.mail_message_id._except_audit_log()

    @dbg.timed
    def write(self, vals):
        dbg.lifecycle.debug("write on %s: keys=%s", dbg.rec(self), dbg.keys(vals))
        self._except_audit_log()
        return super().write(vals)
