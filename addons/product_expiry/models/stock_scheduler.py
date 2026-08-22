# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, models


class StockScheduler(models.AbstractModel):
    _inherit = "stock.scheduler"

    @api.model
    def _get_tasks(self):
        return [*super()._get_tasks(), "_alert_expired_lots"]

    @api.model
    def _alert_expired_lots(self, use_new_cursor=False, company_id=False):
        self.env["stock.lot"]._alert_date_exceeded()
