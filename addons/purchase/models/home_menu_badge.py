from odoo import api, models


class HomeMenuBadge(models.AbstractModel):
    _inherit = "home.menu.badge"

    @api.model
    def _get_badges(self) -> dict[str, int]:
        # The buyer's own RFQs, which is what `draft` spells here.
        return {
            **super()._get_badges(),
            **self._count_for(
                "purchase.menu_purchase_root",
                "purchase.order",
                [("state", "=", "draft"), ("user_id", "=", self.env.uid)],
            ),
        }
