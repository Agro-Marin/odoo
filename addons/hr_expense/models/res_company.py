from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    expense_journal_id = fields.Many2one(
        "account.journal",
        string="Default Expense Journal",
        check_company=True,
        domain="[('type', '=', 'purchase')]",
        help="The company's default journal used when an employee expense is created.",
    )
    company_expense_allowed_payment_channel_ids = fields.Many2many(
        "account.payment.channel",
        string="Payment methods available for expenses paid by company",
        check_company=True,
        domain="[('payment_type', '=', 'outbound'), ('journal_id', '!=', False), ('journal_id.active', '=', True)]",
    )
