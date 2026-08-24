from odoo import models
from odoo.fields import Domain


class MixinStockReplenish(models.AbstractModel):
    _inherit = "mixin.stock.replenish"

    def _get_allowed_route_domain(self):
        """Drop shipping is not a route you can replenish *from*.

        The route is an ordinary `stock.route` record and nothing refuses its deletion,
        so the missing case is reachable rather than theoretical: `env.ref` answers
        `None` -- not an empty recordset -- and reading `.id` off it raised
        `AttributeError` from the wizard's `allowed_route_ids` compute, leaving Replenish
        unusable until someone restored the record. Guarded the way
        `mixin.stock.replenish` already guards its own optional xml-id.
        """
        domains = super()._get_allowed_route_domain()
        dropship_route = self.env.ref(
            "stock_dropshipping.route_drop_shipping",
            raise_if_not_found=False,
        )
        if not dropship_route:
            return domains
        return Domain.AND([domains, Domain("id", "!=", dropship_route.id)])
