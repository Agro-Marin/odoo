# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class SaleReport(models.Model):
    _inherit = 'sale.report'

    website_id = fields.Many2one(
        comodel_name='website',
        readonly=True,
    )
    is_abandoned_cart = fields.Boolean(
        string="Abandoned Cart",
        readonly=True,
    )
    public_categ_ids = fields.Many2many(
        related='product_tmpl_id.public_categ_ids',
        string="eCommerce Categories",
    )

    def _select_additional_fields(self):
        partner_id = self.env.ref('base.public_partner').id
        res = super()._select_additional_fields()
        res['website_id'] = "o.website_id"
        res['is_abandoned_cart'] = f"""
            o.date_order <= (timezone('utc', now()) - ((COALESCE(w.cart_abandoned_delay, '1.0') || ' hour')::INTERVAL))
            AND o.website_id IS NOT NULL
            AND o.state = 'draft'
            AND o.partner_id != {partner_id}
    """
        return res

    def _from_sale(self):
        res = super()._from_sale()
        res += """
            LEFT JOIN website w ON o.website_id=w.id"""
        return res

    def _group_by_sale(self):
        res = super()._group_by_sale()
        res += """,
            o.website_id,
            w.cart_abandoned_delay"""
        return res
