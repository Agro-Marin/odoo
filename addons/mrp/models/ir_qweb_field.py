# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, models


class IrQwebFieldMonetaryOpt(models.AbstractModel):
    """Monetary QWeb widget that renders an *unset* amount as blank."""

    _name = "ir.qweb.field.monetary_opt"
    _inherit = "ir.qweb.field.monetary"
    _description = "QWeb Field Monetary (blank when unset)"

    @api.model
    def value_to_html(self, value, options):
        # The base `monetary` converter raises on False rather than format a boolean as a
        # currency amount, so reports using False as a "not applicable" sentinel opt into
        # this widget. Semantics of the web client's `formatMonetary`: an unset value is
        # blank (0.00 would mislead), a genuine 0 goes to the parent and still renders.
        if value is None or value is False:
            return ""
        return super().value_to_html(value, options)
