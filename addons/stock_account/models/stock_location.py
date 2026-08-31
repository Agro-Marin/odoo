from odoo import api, fields, models
from odoo.fields import Domain


class StockLocation(models.Model):
    _inherit = "stock.location"

    valuation_account_id = fields.Many2one(
        "account.account",
        "Stock Valuation Account",
        domain=[
            (
                "account_type",
                "not in",
                (
                    "asset_receivable",
                    "liability_payable",
                    "asset_cash",
                    "liability_credit_card",
                ),
            )
        ],
        help="Expense account used to re-qualify products removed from stock and sent to this location",
    )
    is_valued_internal = fields.Boolean(
        "Is valued inside the company",
        compute="_compute_is_valued_internal",
        search="_search_is_valued",
    )

    def _search_is_valued(self, operator, value):
        if operator not in ["=", "!="]:
            raise NotImplementedError(self.env._("Invalid search operator or value"))
        positive_operator = (operator == "=" and value) or (
            operator == "!=" and not value
        )
        domain = Domain(
            [
                ("company_id", "!=", False),
                ("usage", "in", ["internal", "transit"]),
            ]
        )
        if positive_operator:
            return domain
        return ~domain

    @api.depends("company_id", "usage")
    def _compute_is_valued_internal(self):
        for location in self:
            location.is_valued_internal = location._should_be_valued()

    def _should_be_valued(self):
        self.check_singleton()
        return bool(self.company_id) and self.usage in ["internal", "transit"]
