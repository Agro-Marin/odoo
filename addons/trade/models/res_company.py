from odoo import fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools.date_utils import get_timedelta

_debug = DebugLog(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    trade_config_id = fields.Many2one(
        comodel_name="trade.config",
        compute="_compute_trade_config_id",
        search="_search_trade_config_id",
    )

    def _search_trade_config_id(self, operator, value):
        return self._search_config_link("trade.config", operator, value)

    def _compute_trade_config_id(self):
        self._compute_config_link("trade_config_id")

    def _get_order_cycle_cutoff_date(self):
        self.check_singleton()
        _debug.logic(
            "order_cycle_cutoff",
            company=self,
            count=self.trade_config_id.order_cycle_count,
            unit=self.trade_config_id.order_cycle_unit,
        )
        return fields.Date.today() - get_timedelta(
            self.trade_config_id.order_cycle_count,
            self.trade_config_id.order_cycle_unit,
        )
