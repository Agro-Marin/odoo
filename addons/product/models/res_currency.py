from odoo import models


class ResCurrency(models.Model):
    _inherit = "res.currency"

    def write(self, vals):
        res = super().write(vals)

        if self and "active" in vals and not vals["active"]:
            self.env["product.pricelist"].search(
                [("currency_id", "in", self.ids)]
            ).action_archive()

        return res

    def _activate_group_multi_currency(self):
        super()._activate_group_multi_currency()
        if not self.env.user.has_group("product.group_product_pricelist"):
            group_user = self.env.ref("base.group_user").sudo()
            group_user._apply_group(self.env.ref("product.group_product_pricelist"))
            self.env["res.company"]._activate_or_create_pricelists()
