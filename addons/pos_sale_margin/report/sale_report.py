from odoo import models


class SaleReport(models.Model):
    _inherit = "sale.report"

    def _fill_pos_fields(self, additional_fields):
        values = super()._fill_pos_fields(additional_fields)
        currency_rate_pos = self._case_value_or_one("pos.currency_rate")
        currency_rate_table = self._case_value_or_one("account_currency_table.rate")
        values["margin"] = (
            f"SUM(l.margin / {currency_rate_pos} * {currency_rate_table})"
        )
        return values
