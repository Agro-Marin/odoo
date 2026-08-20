"""Invoice-Side Order Bridge

``mixin.order.stock`` owns ``incoterm_location`` on the order, so it owns
copying it onto the invoice too.  sale_stock and purchase_stock both carried
the same "first order that has one wins" rule, differing only in the relation
path they walk, and each declared dependencies that did not cover the value
they read.

Only the paths stay in the bridges, contributed through
``_get_order_incoterm_locations()``.
"""

from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    # ─── Compute ──────────────────────────────────────────────────

    def _compute_incoterm_location(self):
        super()._compute_incoterm_location()
        for move in self:
            location = next(
                (loc for loc in move._get_order_incoterm_locations() if loc),
                False,
            )
            # Only overwrite when an order actually carries one: a move may
            # invoice several orders and only some of them set an incoterm, and
            # whatever the base compute resolved is better than blanking it.
            if location:
                move.incoterm_location = location

    def _get_order_incoterm_locations(self):
        """``incoterm_location`` of every order this move invoices.

        Each bridge appends its own order type through ``super()``, so a
        database carrying both answers for whichever orders the move came from
        instead of the later one in the MRO silently winning.

        :returns: list of ``incoterm_location`` values, empty entries included
            — the caller picks the first truthy one
        """
        return []
