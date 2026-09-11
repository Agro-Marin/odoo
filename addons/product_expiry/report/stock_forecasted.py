from odoo import fields, models
from odoo.tools import format_date


class StockForecasted_Product_Product(models.AbstractModel):
    _inherit = "stock.forecasted_product_product"

    def _get_report_header(self, product_template_ids, product_ids, wh_location_ids):
        res = super()._get_report_header(
            product_template_ids, product_ids, wh_location_ids
        )
        products = self.env["product.product"].browse(res["product_variants_ids"])
        res["use_expiration_date"] = any(products.mapped("use_expiration_date"))
        if res["use_expiration_date"]:
            for product in products:
                line = res["product"].get(product.id)
                if not line:
                    continue
                line["to_remove_qty"] = (
                    line["quantity_on_hand"]
                    + line["qty_incoming"]
                    - line["qty_outgoing"]
                    - line["qty_available_virtual"]
                )
        return res

    def _get_domain_quant(self, location_ids, products):
        res = super()._get_domain_quant(location_ids, products)
        if any(products.mapped("use_expiration_date")):
            res += [
                "|",
                ("removal_date", "=", False),
                ("removal_date", ">", fields.Datetime.now()),
            ]
        return res

    def _get_domain_expired_quant(self, location_ids, products):
        return self._get_domain_base_quant(location_ids, products) + [
            ("removal_date", "<=", fields.Datetime.now()),
        ]

    def _prepare_report_line(
        self,
        quantity,
        move_out=None,
        move_in=None,
        replenishment_filled=True,
        product=False,
        reserved_move=False,
        in_transit=False,
        read=True,
    ):
        res = super()._prepare_report_line(
            quantity,
            move_out,
            move_in,
            replenishment_filled,
            product,
            reserved_move,
            in_transit,
            read,
        )
        removal_date = self.env.context.get("removal_date")
        if removal_date:
            res["removal_date"] = (
                removal_date
                if removal_date == -1
                else format_date(self.env, removal_date)
            )
        return res

    def _is_free_stock_lines_required(
        self, product, free_stock, lines, wh_location_ids
    ):
        if super()._is_free_stock_lines_required(
            product, free_stock, lines, wh_location_ids
        ):
            return True
        if not product.use_expiration_date:
            return False
        # The expired and dated-removal lines are built inside
        # `_get_free_stock_lines`, and so is the compensation for stock reserved
        # from expired quants. A product whose free stock nets to zero would
        # otherwise report neither.
        return bool(
            self.env["stock.quant"].search_count(
                self._get_domain_expired_quant(wh_location_ids, product), limit=1
            )
        )

    def _get_free_stock_lines(
        self, product, free_stock, moves_data, wh_location_ids, read
    ):
        res = []
        if product.use_expiration_date:
            expired_qty, reserved_expired = self.env["stock.quant"]._read_group(
                self._get_domain_expired_quant(wh_location_ids, product),
                aggregates=["quantity:sum", "reserved_quantity:sum"],
            )[0]
            unreserved_expired = (expired_qty or 0.0) - (reserved_expired or 0.0)
            reported_qty = 0.0
            if not product.uom_id.is_zero(unreserved_expired):
                res += [
                    self.with_context(removal_date=-1)._prepare_report_line(
                        unreserved_expired, product=product, read=read
                    )
                ]

            to_reduce = sum(d["taken_from_stock"] for d in moves_data.values())

            for removal_date, free_stock_at_date in self.env["stock.quant"]._read_group(
                self._get_domain_quant(wh_location_ids, product),
                ["removal_date:day"],
                ["available_quantity:sum"],
            ):
                to_reduce_here = min(to_reduce, free_stock_at_date)
                to_reduce -= to_reduce_here
                free_stock_at_date -= to_reduce_here
                if removal_date and not product.uom_id.is_zero(free_stock_at_date):
                    res.append(
                        self.with_context(
                            removal_date=removal_date
                        )._prepare_report_line(
                            free_stock_at_date, product=product, read=read
                        )
                    )
                    reported_qty += free_stock_at_date

            # `free_stock` already covers the dated-removal quantities just
            # broken out above; without this, the undivided line added by
            # super() below double-counts them. Expired quants are NOT in it:
            # `_get_domain_quant` filters them out, which is why only the
            # dated buckets feed `reported_qty`.
            free_stock += reserved_expired - reported_qty
            if res and product.uom_id.is_zero(free_stock):
                # Everything free is accounted for by the lines above; an
                # undivided line here would be a bare "Free Stock 0.00" row.
                return res
        return res + super()._get_free_stock_lines(
            product, free_stock, moves_data, wh_location_ids, read
        )
