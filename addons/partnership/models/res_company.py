from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    partnership_config_id = fields.Many2one(
        comodel_name="partnership.config",
        compute="_compute_partnership_config_id",
        search="_search_partnership_config_id",
    )

    def _search_partnership_config_id(self, operator, value):
        return self._search_config_link("partnership.config", operator, value)

    def _compute_partnership_config_id(self):
        self._compute_config_link("partnership_config_id")
