from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    is_donation = fields.Boolean(
        string="Is Donation", related="payment_transaction_id.is_donation"
    )
