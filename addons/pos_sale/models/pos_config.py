from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    crm_team_id = fields.Many2one(
        "crm.team",
        string="Sales Team",
        ondelete="set null",
        index="btree_not_null",
        help="This Point of sale's sales will be related to this Sales Team.",
    )
    down_payment_product_id = fields.Many2one(
        "product.product",
        string="Down Payment Product",
        help="This product will be used as down payment on a sale order.",
    )
    default_product_id = fields.Many2one(
        "product.product",
        string="Default Product",
        default=lambda self: self._default_sol_product(),
        help="A register line always carries a product, so this one stands in "
        "for a sale order line that has only a description. The line keeps "
        "showing the description it came with.",
    )

    @api.model
    def _default_sol_product(self):
        return self.env.ref("pos_sale.default_sol_product", raise_if_not_found=False)

    @api.model
    def _fill_default_sol_product(self):
        """Give every register that has none the stand-in product.

        The field default only reaches registers created from here on, and the
        ones point_of_sale ships were created before this module -- and this
        field -- existed. Called from the post-init hook on install and from
        `migrations/1.2` on upgrade. A register with no stand-in silently drops
        description-only sale order lines again.
        """
        product = self._default_sol_product()
        if not product:
            return self.env["pos.config"]
        configs = (
            self.env["pos.config"]
            .with_context(active_test=False)
            .search([("default_product_id", "=", False)])
        )
        configs.write({"default_product_id": product.id})
        return configs

    def _get_special_products(self):
        res = super()._get_special_products()
        configs = self.env["pos.config"].search([])
        return res | configs.down_payment_product_id | configs.default_product_id

    @api.model
    def _update_downpayment_product(self):
        pos_config = self.env.ref(
            "point_of_sale.pos_config_main", raise_if_not_found=False
        )
        downpayment_product = self.env.ref(
            "pos_sale.default_downpayment_product", raise_if_not_found=False
        )
        if pos_config and downpayment_product:
            pos_config.write({"down_payment_product_id": downpayment_product.id})

    @api.model
    def load_onboarding_furniture_scenario(self, with_demo_data=True):
        res = super().load_onboarding_furniture_scenario(with_demo_data)
        self._update_downpayment_product()
        return res
