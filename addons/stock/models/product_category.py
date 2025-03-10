from odoo import _, api, fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    removal_strategy_id = fields.Many2one(
        comodel_name="product.removal",
        string="Force Removal Strategy",
        tracking=True,
        help="Set a specific removal strategy that will be used regardless of the source location for this product category.\n\n"
        "FIFO: products/lots that were stocked first will be moved out first.\n"
        "LIFO: products/lots that were stocked last will be moved out first.\n"
        "Closest location: products/lots closest to the target location will be moved out first.\n"
        "FEFO: products/lots with the closest removal date will be moved out first "
        '(the availability of this method depends on the "Expiration Dates" setting).\n'
        "Least Packages: FIFO but with the least number of packages possible when there are several packages containing the same product.",
    )
    route_ids = fields.Many2many(
        "stock.route",
        "stock_route_categ",
        "categ_id",
        "route_id",
        "Routes",
        domain=[("product_categ_selectable", "=", True)],
    )
    parent_route_ids = fields.Many2many(
        comodel_name="stock.route",
        string="Parent Routes",
        compute="_compute_parent_route_ids",
    )
    total_route_ids = fields.Many2many(
        comodel_name="stock.route",
        string="Total routes",
        compute="_compute_total_route_ids",
        search="_search_total_route_ids",
        readonly=True,
    )
    packaging_reserve_method = fields.Selection(
        [
            ("full", "Reserve Only Full Packagings"),
            ("partial", "Reserve Partial Packagings"),
        ],
        string="Reserve Packagings",
        default="partial",
        help="Reserve Only Full Packagings: will not reserve partial packagings. If customer orders 2 pallets of 1000 units each and you only have 1600 in stock, then only 1000 will be reserved\n"
        "Reserve Partial Packagings: allow reserving partial packagings. If customer orders 2 pallets of 1000 units each and you only have 1600 in stock, then 1600 will be reserved",
    )
    putaway_rule_ids = fields.One2many(
        comodel_name="stock.putaway.rule",
        inverse_name="category_id",
        string="Putaway Rules",
    )
    filter_for_stock_putaway_rule = fields.Boolean(
        string="stock.putaway.rule",
        store=False,
        search="_search_filter_for_stock_putaway_rule",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("parent_id")
    def _compute_parent_route_ids(self):
        for category in self:
            base_cat = category
            routes = self.env["stock.route"]
            while base_cat.parent_id:
                base_cat = base_cat.parent_id
                routes |= base_cat.route_ids
            category.parent_route_ids = routes - category.route_ids

    @api.depends("route_ids", "parent_route_ids")
    def _compute_total_route_ids(self):
        for category in self:
            category.total_route_ids = category.route_ids | category.parent_route_ids

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_total_route_ids(self, operator, value):
        categories = self.env["product.category"].sudo().search([])
        categ_ids = categories.filtered_domain(
            [("total_route_ids", operator, value)]
        ).ids
        return [("id", "in", categ_ids)]

    def _search_filter_for_stock_putaway_rule(self, operator, value):
        assert operator == "="
        assert value
        active_model = self.env.context.get("active_model")

        if active_model in (
            "product.template",
            "product.product",
        ) and self.env.context.get("active_id"):
            product = self.env[active_model].browse(self.env.context.get("active_id"))
            product = product.exists()
            if product:
                return [("id", "=", product.categ_id.id)]

        return []
