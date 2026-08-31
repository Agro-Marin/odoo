from odoo import models
from odoo.fields import Domain


class MixinStockReplenish(models.AbstractModel):
    _inherit = "mixin.stock.replenish"

    def _get_allowed_route_domain(self):
        domains = super()._get_allowed_route_domain()
        dropship_route = self.env.ref(
            "stock_dropshipping.route_drop_shipping",
            raise_if_not_found=False,
        )
        if not dropship_route:
            return domains
        return Domain.AND([domains, Domain("id", "!=", dropship_route.id)])
