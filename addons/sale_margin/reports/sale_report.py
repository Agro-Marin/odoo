from odoo import fields, models
from odoo.tools import frozendict


class SaleReport(models.Model):
    _inherit = "sale.report"
    _depends = frozendict(
        {
            "sale.order.line": ["margin"],
        }
    )

    margin = fields.Float()

    def _get_fields_select(self):
        res = super()._get_fields_select()
        res["margin"] = f"""SUM(l.margin
            / {self._case_value_or_one("o.currency_rate")}
            * {self._case_value_or_one("account_currency_table.rate")})
        """
        return res
