from odoo import api, models
from odoo.fields import Domain


class StockScheduler(models.AbstractModel):
    _inherit = "stock.scheduler"

    @api.model
    def _get_domain_moves_to_assign(self, company_id):
        domain = super()._get_domain_moves_to_assign(company_id)
        return domain & Domain("production_id", "=", False)
