"""
Picking-Level Order Bridge

sale_stock and purchase_stock both need "when was the source order placed?"
on a transfer, and both used to declare it themselves.  Since both modules
are ``auto_install``, those two copies always coexisted and the later one in
the MRO silently won: ``delay_pass`` on a receipt answered with the sale
branch, which has no ``sale_id`` and so fell back to ``now()``.

Declared once here instead, with per-order-type hooks the bridges extend.
"""

from odoo import api, fields, models
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # ─── Fields ───────────────────────────────────────────────────

    delay_pass = fields.Datetime(
        compute="_compute_delay_pass",
        search="_search_delay_pass",
        copy=False,
        index=True,
    )

    # ─── Compute ──────────────────────────────────────────────────

    def _compute_delay_pass(self):
        for picking in self:
            picking.delay_pass = (
                picking._get_source_order_date() or fields.Datetime.now()
            )

    def _get_source_order_date(self):
        """Order date of the document this transfer originates from.

        Each order bridge extends this with an ``or super()`` chain, so a
        database carrying both sale_stock and purchase_stock answers for
        whichever order type the transfer actually came from.

        :returns: a ``Datetime``, or ``False`` when the transfer has no order
        """
        self.ensure_one()
        return False

    # ─── Search ───────────────────────────────────────────────────

    @api.model
    def _search_delay_pass(self, operator, value):
        paths = self._get_source_order_date_paths()
        if not paths:
            return Domain.FALSE
        return Domain.OR([(path, operator, value)] for path in paths)

    @api.model
    def _get_source_order_date_paths(self):
        """Field paths mirroring :meth:`_get_source_order_date`, for searching.

        Kept separate because the compute walks one record while the search
        must reach every order type at once — the disjunction of these paths
        is what ``_search_delay_pass`` builds.
        """
        return []
