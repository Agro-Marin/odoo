# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, models


class IrQwebFieldMonetaryOpt(models.AbstractModel):
    """Monetary QWeb widget that renders an *unset* amount as blank.

    The base ``monetary`` converter deliberately rejects booleans (a stray
    ``True``/``False`` must never be silently formatted as a currency amount),
    so it raises on ``False``. Reports that legitimately use ``False`` as a
    "not applicable" sentinel for a monetary column can opt into this
    ``monetary_opt`` widget instead. Its semantics mirror the web client's
    ``formatMonetary`` (``@web/fields/formatters``): an unset value renders
    empty — a ``0.00`` there would be misleading — while a genuine ``0`` is
    delegated to the parent converter and still renders.

    This keeps the PDF and OWL renderings of the MO Overview report in sync;
    both now blank the same "not applicable" cost cells instead of one
    rendering blank and the other raising.
    """

    _name = "ir.qweb.field.monetary_opt"
    _inherit = "ir.qweb.field.monetary"
    _description = "QWeb Field Monetary (blank when unset)"

    @api.model
    def value_to_html(self, value, options):
        if value is None or value is False:
            return ""
        return super().value_to_html(value, options)
