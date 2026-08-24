from odoo import fields, models


class PaymentMethod(models.Model):
    _name = 'payment.method'
    _inherit = ['payment.method', 'mixin.fiscal.country.codes']

    l10n_ec_sri_payment_id = fields.Many2one(
        comodel_name="l10n_ec.sri.payment",
        string="SRI Payment Method",
    )
