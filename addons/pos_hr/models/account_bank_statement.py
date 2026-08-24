from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    employee_id = fields.Many2one('hr.employee', string="Employee", help="The employee who made the cash move.")
