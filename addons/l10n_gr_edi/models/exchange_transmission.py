from odoo import fields, models


class ExchangeTransmission(models.Model):
    _inherit = "exchange.transmission"

    l10n_gr_edi_mark = fields.Char(
        string="myDATA Mark",
        help="The authority's identifier for the invoice. On a classification "
        "it is an input we must quote, not a verdict on what we sent -- which "
        "is why it is not `reference`.",
    )
    l10n_gr_edi_url = fields.Char(string="myDATA QR URL")
