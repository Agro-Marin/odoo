# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, models
from odoo.fields import Domain


class StockScheduler(models.AbstractModel):
    _inherit = "stock.scheduler"

    @api.model
    def _get_moves_to_assign_domain(self, company_id):
        # A subcontracted receipt is reserved by the subcontracting flow.
        domain = super()._get_moves_to_assign_domain(company_id)
        return domain & Domain("is_subcontract", "=", False)
