from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    margin = fields.Float(
        "Margin",
        compute="_compute_margin",
        min_display_digits="Product Price",
        store=True,
        groups="base.group_user",
        precompute=True,
    )
    margin_percent = fields.Float(
        "Margin (%)",
        compute="_compute_margin",
        store=True,
        groups="base.group_user",
        precompute=True,
    )
    purchase_price = fields.Float(
        string="Cost",
        compute="_compute_purchase_price",
        min_display_digits="Product Price",
        store=True,
        readonly=False,
        copy=False,
        precompute=True,
        groups="base.group_user",
    )

    @api.depends("product_id", "company_id", "currency_id", "product_uom_id")
    def _compute_purchase_price(self):
        for line in self:
            if not line.product_id:
                line.purchase_price = 0.0
                continue
            line = line.with_company(line.company_id)

            # Convert the cost to the line UoM
            product_cost = line.product_id.uom_id._compute_price(
                line.product_id.standard_price,
                line.product_uom_id,
            )

            line.purchase_price = line._convert_to_sol_currency(
                product_cost, line.product_id.cost_currency_id
            )

    @api.depends(
        "price_subtotal",
        "price_unit",
        "product_qty",
        "purchase_price",
        "qty_transferred",
    )
    def _compute_margin(self):
        for line in self:
            # `product_qty`, `qty_transferred` and `purchase_price` are all in the
            # LINE's unit -- `_compute_purchase_price` converts the cost into
            # `product_uom_id` explicitly. `product_uom_qty` is the same quantity
            # in the product's REFERENCE unit, so pairing it with a per-line-unit
            # price multiplies the conversion factor in twice.
            # Find alternative calculation when line is added to order from delivery
            if line.qty_transferred and not line.product_qty:
                calculated_subtotal = line.price_unit * line.qty_transferred
                line.margin = calculated_subtotal - (
                    line.purchase_price * line.qty_transferred
                )
                line.margin_percent = (
                    calculated_subtotal and line.margin / calculated_subtotal
                )
            else:
                line.margin = line.price_subtotal - (
                    line.purchase_price * line.product_qty
                )
                line.margin_percent = (
                    line.price_subtotal and line.margin / line.price_subtotal
                )
