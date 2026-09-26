from odoo import fields, models
from odoo.tools import frozendict


class SaleAgreement(models.Model):
    _name = "sale.agreement"
    _inherit = ["mixin.agreement"]
    _description = "Sales Agreement"

    user_id = fields.Many2one(string="Salesperson")
    order_count = fields.Count(
        count_of="order_ids",
        string="Number of Orders",
    )
    order_ids = fields.One2many(
        comodel_name="sale.order",
        inverse_name="agreement_id",
        string="Sales Orders",
    )
    line_ids = fields.One2many(
        comodel_name="sale.agreement.line",
        inverse_name="agreement_id",
        string="Products to Sell",
        copy=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        related="line_ids.product_id",
        string="Product",
    )

    def _get_sequence_code(self, agreement_type):
        return {"blanket_order": "sale.agreement.blanket.order"}[agreement_type]

    def _get_partner_currency(self, partner):
        return partner.property_product_pricelist.currency_id


class SaleAgreementLine(models.Model):
    _name = "sale.agreement.line"
    _inherit = ["mixin.agreement.line"]
    _description = "Sales Agreement Line"
    _access_anchors = frozendict(
        {
            "company": models.Anchor("company_id", shared=False),
        }
    )

    product_id = fields.Many2one(domain=[("sale_ok", "=", True)])
    agreement_id = fields.Many2one(
        comodel_name="sale.agreement",
        string="Sales Agreement",
        index=True,
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        related="agreement_id.company_id",
        string="Company",
        readonly=True,
    )
