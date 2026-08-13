from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _get_default_warehouse_id(self):
        return self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
