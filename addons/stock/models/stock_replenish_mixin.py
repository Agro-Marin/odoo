from odoo import api, fields, models
from odoo.fields import Domain


class StockReplenishMixin(models.AbstractModel):
    _name = "stock.replenish.mixin"
    _description = "Product Replenish Mixin"

    route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Preferred Route",
        check_company=True,
        help="Apply specific route for the replenishment instead of product's default routes.",
    )
    allowed_route_ids = fields.Many2many(
        comodel_name="stock.route",
        compute="_compute_allowed_route_ids",
    )

    @api.depends("product_id", "product_tmpl_id")
    def _compute_allowed_route_ids(self):
        domain = self._get_allowed_route_domain()
        route_ids = self.env["stock.route"].search(domain)
        self.allowed_route_ids = route_ids

    # TODO: remove dynamic domain
    # Overridden in 'Drop Shipping' and 'Dropship and Subcontracting Management'
    # to exclude the dropshipping route from the allowed routes.
    def _get_allowed_route_domain(self):
        # raise_if_not_found=False: the record is deletable and the rest of the
        # module already guards this ref — a missing transit location must not
        # crash the replenish wizard.
        inter_company_location = self.env.ref(
            "stock.stock_location_inter_company", raise_if_not_found=False
        )

        base_domain = Domain("product_selectable", "=", True)
        if self.warehouse_id:
            wh_route_ids = self.warehouse_id.route_ids.filtered(
                lambda r: r._is_valid_resupply_route_for_product(self.product_id)
            ).ids
            if wh_route_ids:
                base_domain |= Domain("id", "in", wh_route_ids)

        domains = [
            base_domain,
            # "Any rule delivering inside a warehouse" is intended `any`
            # semantics and stays a plain o2m path condition.
            Domain("rule_ids.location_dest_id.warehouse_id", "!=", False),
        ]
        if inter_company_location:
            # `not any`, not a `!=` path condition: `rule_ids.location_src_id
            # != X` matches routes having ANY rule whose source differs from X
            # (i.e. almost all of them, inter-company ones included). The intent
            # is routes with NO rule touching the inter-company location.
            domains += [
                Domain(
                    "rule_ids",
                    "not any",
                    [("location_src_id", "=", inter_company_location.id)],
                ),
                Domain(
                    "rule_ids",
                    "not any",
                    [("location_dest_id", "=", inter_company_location.id)],
                ),
            ]
        return Domain.AND(domains)
