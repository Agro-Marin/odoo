from odoo import fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Cashier",
        related="pos_order_id.employee_id",
        store=True,
        index=True,
    )
