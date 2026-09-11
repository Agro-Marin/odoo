from odoo import models


class PaymentToken(models.Model):
    _inherit = "payment.token"

    def _get_available_tokens(self, *args, is_express_checkout=False, **kwargs):
        if is_express_checkout:
            return self.env["payment.token"]

        return super()._get_available_tokens(*args, **kwargs)
