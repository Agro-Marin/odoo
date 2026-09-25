from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    purchase_config_id = fields.Many2one(
        comodel_name="purchase.config",
        compute="_compute_purchase_config_id",
        search="_search_purchase_config_id",
    )

    def _search_purchase_config_id(self, operator, value):
        return self._search_config_link("purchase.config", operator, value)

    def _compute_purchase_config_id(self):
        self._compute_config_link("purchase_config_id")
