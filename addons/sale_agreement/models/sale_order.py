from odoo import fields, models


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "mixin.order.agreement"]

    agreement_id = fields.Many2one(
        comodel_name="sale.agreement",
        string="Agreement",
        index="btree_not_null",
        copy=False,
        domain="[('state', '=', 'confirmed'), ('partner_id', 'in', (partner_id, False)), ('company_id', '=', company_id)]",
        check_company=True,
    )
    agreement_type = fields.Selection(related="agreement_id.agreement_type")
