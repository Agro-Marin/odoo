from collections import defaultdict

from odoo import _, api, fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    lot_valuated = fields.Boolean(
        related="product_id.lot_valuated", readonly=True, store=False
    )
    avg_cost = fields.Monetary(
        string="Average Cost",
        compute="_compute_value",
        compute_sudo=True,
        store=False,
        readonly=True,
        currency_field="company_currency_id",
    )
    total_value = fields.Monetary(
        string="Total Value",
        compute="_compute_value",
        compute_sudo=True,
        currency_field="company_currency_id",
    )
    company_currency_id = fields.Many2one(
        "res.currency",
        "Valuation Currency",
        compute="_compute_value",
        compute_sudo=True,
    )
    standard_price = fields.Float(
        "Cost",
        company_dependent=True,
        min_display_digits="Product Price",
        groups="base.group_user",
        help="""Value of the lot (automatically computed in AVCO).
        Used to value the product when the purchase cost is not known (e.g. inventory adjustment).
        Used to compute margins on sale orders.""",
    )

    @api.depends(
        "product_id.lot_valuated",
        "product_id.product_tmpl_id.lot_valuated",
        "product_id.stock_move_ids.value",
        "standard_price",
    )
    @api.depends_context("to_date", "company", "warehouse_id")
    def _compute_value(self):
        """Compute totals of multiple svl related values"""
        company_id = self.env.company
        self.company_currency_id = company_id.currency_id
        at_date = fields.Datetime.to_datetime(self.env.context.get("to_date"))

        # AVCO lots are collected per product and replayed together below: one pass
        # over a product's moves values all of its lots, where a pass per lot costs
        # a full round of queries each.
        avco_lots_by_product = defaultdict(lambda: self.env["stock.lot"])
        quantities_by_lot_id = {}
        for lot in self:
            if not lot.lot_valuated:
                lot.total_value = 0.0
                lot.avg_cost = 0.0
                continue
            valuated_product = lot.product_id.with_context(
                at_date=at_date, lot_id=lot.id
            )
            qty_valued = lot.product_qty
            qty_available = lot.with_context(warehouse_id=False).product_qty
            quantities_by_lot_id[lot.id] = (qty_valued, qty_available)
            if valuated_product.uom_id.is_zero(qty_valued):
                lot.total_value = 0
                lot.avg_cost = 0.0
            elif (
                valuated_product.cost_method == "standard"
                or valuated_product.uom_id.is_zero(qty_available)
            ):
                lot.total_value = lot.standard_price * qty_valued
                lot.avg_cost = lot.standard_price
            elif valuated_product.cost_method == "average":
                # Key on the bare product: a recordset hashes on its ids alone, so
                # keying on `valuated_product` would collapse the per-lot contexts
                # onto whichever lot landed in the dict first.
                avco_lots_by_product[lot.product_id] |= lot
            else:
                fifo_value = valuated_product.with_context(
                    warehouse_id=False
                )._run_fifo(
                    qty_available,
                    at_date=at_date,
                    lot=lot.with_context(warehouse_id=False),
                )
                lot.total_value = fifo_value * qty_valued / qty_available
                lot.avg_cost = fifo_value / qty_available if qty_available else 0.0

        for product, lots in avco_lots_by_product.items():
            unit_cost_by_lot_id, value_by_lot_id = product.with_context(
                at_date=at_date, warehouse_id=False
            )._run_average_batch(
                at_date=at_date,
                lots=lots.with_context(warehouse_id=False),
                force_recompute=True,
            )
            for lot in lots:
                qty_valued, qty_available = quantities_by_lot_id[lot.id]
                lot.total_value = (
                    value_by_lot_id.get(lot.id, 0) * qty_valued / qty_available
                )
                lot.avg_cost = unit_cost_by_lot_id.get(lot.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        lots = super().create(vals_list)
        for product, lots_by_product in lots.grouped("product_id").items():
            if product.lot_valuated:
                lots_by_product.filtered(
                    lambda lot: not lot.standard_price
                ).with_context(disable_auto_revaluation=True).write(
                    {
                        "standard_price": product.standard_price,
                    }
                )
        return lots

    def write(self, vals):
        old_price = False
        if "standard_price" in vals and not self.env.context.get(
            "disable_auto_revaluation"
        ):
            old_price = {lot: lot.standard_price for lot in self}
        res = super().write(vals)
        if old_price:
            self._change_standard_price(old_price)
        return res

    def _update_standard_price(self):
        # TODO: Add extra value and extra quantity kwargs to avoid total recomputation
        # AVCO lots are replayed per product in one pass, as in `_compute_value`:
        # this runs on every receipt of a lot-valuated product, so a pass per lot
        # would put a full round of queries per lot on the validation path.
        avco_lots_by_product = defaultdict(lambda: self.env["stock.lot"])
        for lot in self:
            lot = lot.with_context(disable_auto_revaluation=True)
            if not lot.product_id.lot_valuated:
                continue
            if lot.product_id.cost_method == "standard":
                if not lot.standard_price:
                    lot.standard_price = lot.product_id.standard_price
                continue
            if lot.product_id.cost_method == "average":
                avco_lots_by_product[lot.product_id] |= lot
            else:
                lot.standard_price = lot.product_id._run_fifo_batch(lot=lot)[0].get(
                    lot.id, lot.standard_price
                )

        for product, lots in avco_lots_by_product.items():
            unit_cost_by_lot_id = product._run_average_batch(
                lots=lots, force_recompute=True
            )[0]
            for lot in lots.with_context(disable_auto_revaluation=True):
                lot.standard_price = unit_cost_by_lot_id.get(lot.id, 0)

    def _change_standard_price(self, old_price):
        """Helper to create the stock valuation layers and the account moves
        after an update of standard price.

        :param old_price: mapping ``{lot: previous standard price}``
        """
        product_values = []
        for lot in self:
            lot_old_price = old_price.get(lot)
            if (
                lot.product_id.cost_method != "average"
                or lot.standard_price == lot_old_price
            ):
                continue
            product = lot.product_id
            product_values.append(
                {
                    "product_id": product.id,
                    "lot_id": lot.id,
                    "value": lot.standard_price,
                    # Company-dependent price -> stamp the company it was written
                    # under, not the product's. See ProductProduct._change_standard_price.
                    "company_id": self.env.company.id,
                    "date": fields.Datetime.now(),
                    "description": _(
                        "%(lot)s price update from %(old_price)s to %(new_price)s by %(user)s",
                        lot=lot.name,
                        old_price=lot_old_price,
                        new_price=lot.standard_price,
                        user=self.env.user.name,
                    ),
                }
            )

        # Records a price the caller just wrote; must not re-trigger the recompute.
        self.env["product.value"].sudo().with_context(
            disable_auto_revaluation=True
        ).create(product_values)
