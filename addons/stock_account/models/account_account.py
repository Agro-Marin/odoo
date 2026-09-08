from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = "account.account"

    account_stock_variation_id = fields.Many2one(
        "account.account",
        string="Variation Account",
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
        help="At closing, register the inventory variation of the period into a specific account",
    )
    account_stock_variation_active = fields.Boolean(
        string="Variation Account Active",
        related="account_stock_variation_id.active",
    )
    account_stock_expense_id = fields.Many2one(
        "account.account",
        string="Expense Account",
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
        help="Counterpart used at closing for accounting adjustments to inventory valuation.",
    )
    account_stock_expense_active = fields.Boolean(
        string="Expense Account Active",
        related="account_stock_expense_id.active",
    )
