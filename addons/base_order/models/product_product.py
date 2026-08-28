from datetime import timedelta

from odoo import fields, models
from odoo.fields import Domain

#: Fixed lookback window for `_compute_ordered_qty`, intentionally
#: independent of `res.company.order_cycle_interval_number/type` (which
#: drives a separate, configurable "gone quiet" cutoff on `res.partner`).
ORDERED_QTY_WINDOW_DAYS = 365


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _compute_is_in_order(self, line_model, field_name):
        order_id = self.env.context.get("order_id")
        if not order_id:
            self[field_name] = False
            return

        counts = {
            product.id: count
            for product, count in self.env[line_model]._read_group(
                domain=[("order_id", "=", order_id)],
                groupby=["product_id"],
                aggregates=["__count"],
            )
        }
        for product in self:
            product[field_name] = bool(counts.get(product.id))

    def _search_is_in_order(self, line_model):
        order_id = self.env.context.get("order_id")
        if not order_id:
            return [("id", "in", [])]
        product_ids = (
            self.env[line_model]
            .search_fetch([("order_id", "=", order_id)], ["product_id"])
            .product_id.ids
        )
        return [("id", "in", product_ids)]

    def _compute_ordered_qty(self, field_name, model, group, date_field, domain):
        self[field_name] = 0.0
        if not self.env.user.has_group(group):
            return

        date_from = fields.Date.today() - timedelta(days=ORDERED_QTY_WINDOW_DAYS)
        quantities = {
            product.id: qty
            for product, qty in self.env[model]._read_group(
                Domain.AND(
                    [
                        domain,
                        [
                            ("product_id", "in", self.ids),
                            (date_field, ">=", date_from),
                        ],
                    ],
                ),
                ["product_id"],
                ["product_uom_qty:sum"],
            )
        }
        for product in self:
            if product.id:
                product[field_name] = product.uom_id.round(
                    quantities.get(product.id, 0),
                )

    def _has_order_lines(self, line_model):
        return bool(
            self.env[line_model]
            .sudo()
            .search_count([("product_id", "in", self.ids)], limit=1),
        )

    def _update_uom_on_order_lines(self, line_model, to_uom_id):
        self._restamp_uom(line_model, to_uom_id).flush_recordset()
