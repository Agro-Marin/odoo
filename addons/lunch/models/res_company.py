from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    lunch_config_id = fields.Many2one(
        comodel_name="lunch.config",
        compute="_compute_lunch_config_id",
        search="_search_lunch_config_id",
    )

    def _search_lunch_config_id(self, operator, value):
        return self._search_config_link("lunch.config", operator, value)

    def _compute_lunch_config_id(self):
        self._compute_config_link("lunch_config_id")
