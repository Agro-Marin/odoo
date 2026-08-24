from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    use_expiration_date = fields.Boolean(related="product_id.use_expiration_date")

    def _read_qties(self, date, wh):
        res = super(
            SaleOrderLine, self.with_context(fresh_qty_forecast=True)
        )._read_qties(date, wh)
        if any(self.mapped("use_expiration_date")):
            # res (from super()._read_qties) and the read() below both derive from
            # self.mapped('product_id'), so they are equal-length and same-order
            for res_record, read_record in zip(
                res,
                self.mapped("product_id")
                .with_context(warehouse_id=wh)
                .read(["qty_free"]),
                strict=True,
            ):
                res_record["qty_free"] = read_record["qty_free"]
        return res
