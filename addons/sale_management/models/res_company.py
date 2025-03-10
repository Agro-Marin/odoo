from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"
    _check_company_auto = True

    sale_order_template_id = fields.Many2one(
        comodel_name="sale.order.template",
        string="Default Sale Template",
        check_company=True,
        domain="[('company_id', 'in', (False, id)]",
    )
