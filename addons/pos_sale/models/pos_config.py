from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    def _default_down_payment_product_id(self):
        return self.env.ref(
            "pos_sale.default_downpayment_product", raise_if_not_found=False
        )

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
        default=_default_down_payment_product_id,
        help="This product will be used as down payment on a sale order.",
    )

    def _get_special_products(self):
        res = super()._get_special_products()
        return res | self.env["pos.config"].search([]).mapped("down_payment_product_id")

    @api.model
    def _update_downpayment_product(self):
        downpayment_product = self._default_down_payment_product_id()
        if not downpayment_product:
            return
        # Only the registers that have none: a product picked by hand is a
        # decision, and this runs again every time the onboarding scenario does.
        self.with_context(active_test=False).search(
            [("down_payment_product_id", "=", False)]
        ).write({"down_payment_product_id": downpayment_product.id})

    @api.model
    def load_onboarding_furniture_scenario(self, with_demo_data=True):
        res = super().load_onboarding_furniture_scenario(with_demo_data)
        self._update_downpayment_product()
        return res
