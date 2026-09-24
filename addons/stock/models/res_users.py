from odoo import models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    def _get_default_warehouse_id(self):
        warehouse = self.env["stock.warehouse"]._get_default_for_company(
            self.env.company
        )
        _debug.logic(
            "default_warehouse", company=self.env.company.id, warehouse=warehouse.id
        )
        return warehouse
