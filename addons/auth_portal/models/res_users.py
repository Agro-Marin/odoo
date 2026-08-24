from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    def get_totp_invite_url(self):
        if not self._is_internal():
            return "/my/security"
        else:
            return super().get_totp_invite_url()
