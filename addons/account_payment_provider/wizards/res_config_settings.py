from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pay_invoices_online = fields.Boolean(
        config_parameter="account_payment_provider.enable_portal_payment"
    )
