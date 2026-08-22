from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _compute_incoterm_location(self):
        super()._compute_incoterm_location()
        for move in self:
            location = next(
                (loc for loc in move._get_order_incoterm_locations() if loc),
                False,
            )
            if location:
                move.incoterm_location = location

    def _get_order_incoterm_locations(self):
        return []
