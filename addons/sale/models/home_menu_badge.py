from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @api.model
    def _get_badges(self) -> dict[str, int]:
        # The salesperson's own quotations. `draft` is what a quotation is on
        # this fork -- `done` is the confirmed order, where upstream says
        # `sale` -- and it is the state the Quotations menu already filters on.
        return {
            **super()._get_badges(),
            **self._count_for(
                "sale.sale_menu_root",
                "sale.order",
                [("state", "=", "draft"), ("user_id", "=", self.env.uid)],
            ),
        }
