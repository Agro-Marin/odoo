from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    # FIELDS

    # Shared by sale and purchase invoice lines; declared here so the generic
    # ``order.line.invoice.mixin._prepare_aml_vals`` can set it without either
    # module installed.
    is_downpayment = fields.Boolean()
