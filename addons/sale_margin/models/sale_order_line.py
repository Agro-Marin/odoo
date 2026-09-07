from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    margin = fields.Float(
        "Margin",
        compute="_compute_margin",
        min_display_digits="Product Price",
        store=True,
        readonly=False,
        copy=False,
        groups="base.group_user",
        precompute=True,
    )
    margin_percent = fields.Float(
        "Margin (%)",
        compute="_compute_margin_percent",
        store=True,
        readonly=False,
        copy=False,
        groups="base.group_user",
        precompute=True,
        aggregator="avg",
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
            # A combo master line prices at 0 by design (`_get_price_display`) --
            # its real revenue and cost live on the linked combo-item lines
            # (`_get_lines_with_price`). Costing it from its own product's
            # `standard_price` would create a phantom cost with no matching
            # revenue.
            if not line.product_id or line.product_type == "combo":
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
            line.margin = line._get_margin_revenue() - (
                line.purchase_price * line._get_margin_qty()
            )

    @api.depends(
        "margin",
        "price_subtotal",
        "price_unit",
        "product_qty",
        "qty_transferred",
    )
    def _compute_margin_percent(self):
        for line in self:
            # The percent reads `_get_margin_revenue()` on its own, so it is
            # triggered by everything that feeds it and not only by `margin`.
            revenue = line._get_margin_revenue()
            line.margin_percent = (
                float_round(line.margin / revenue, precision_digits=4)
                if revenue
                else 0.0
            )

    @api.onchange("margin")
    def _onchange_margin(self):
        computed_margin = self._get_margin_revenue() - (
            self.purchase_price * self._get_margin_qty()
        )
        if not self.currency_id.compare_amounts(computed_margin, self.margin):
            # The onchange fired because `_compute_margin` ran, not because
            # anyone typed: the current price already yields this margin.
            return

        self._check_a_price_can_carry_a_margin()
        margin_per_qty = self.margin / self._get_margin_qty()
        self._set_price_incl_taxes(
            (margin_per_qty + self.purchase_price) / self._get_discount_factor()
        )

    @api.onchange("margin_percent")
    def _onchange_margin_percent(self):
        revenue = self._get_margin_revenue()
        if not revenue or not float_compare(
            self.margin_percent, self.margin / revenue, precision_digits=4
        ):
            # Same guard as `_onchange_margin`, at the precision the percent is
            # rounded to. `compare_amounts` would use the currency's rounding,
            # and 0.01 on a ratio is a half-point deadband on a percentage.
            return

        if self.margin_percent == 1:
            if self.purchase_price:
                raise UserError(
                    self.env._(
                        "A line that costs something cannot be sold at a 100%"
                        " margin. Set the cost to zero, or lower the margin."
                    )
                )
            # A line that costs nothing is already at 100%: no price to solve for.
            return

        self._check_a_price_can_carry_a_margin()
        self._set_price_incl_taxes(
            self.purchase_price
            / ((1 - self.margin_percent) * self._get_discount_factor())
        )

    def _get_margin_revenue(self):
        """Revenue the margin is measured against.

        A line added to the order from a delivery carries its quantity on
        `qty_transferred` and nothing on `product_qty`, so `price_subtotal` is
        zero and the revenue has to be rebuilt from the unit price.

        :rtype: float
        """
        self.check_singleton()
        if self.qty_transferred and not self.product_qty:
            return self.price_unit * self.qty_transferred
        return self.price_subtotal

    def _get_margin_qty(self):
        """Quantity the cost is multiplied by, in the LINE's unit.

        `product_qty`, `qty_transferred` and `purchase_price` are all in the
        line's unit -- `_compute_purchase_price` converts the cost into
        `product_uom_id` explicitly. `product_uom_qty` is the same quantity in
        the product's REFERENCE unit, so pairing it with a per-line-unit price
        multiplies the conversion factor in twice.

        :rtype: float
        """
        self.check_singleton()
        if self.qty_transferred and not self.product_qty:
            return self.qty_transferred
        return self.product_qty

    def _get_discount_factor(self):
        """What the discount leaves of the unit price, as a factor.

        :rtype: float
        """
        self.check_singleton()
        return 1 - self.discount / 100

    def _check_a_price_can_carry_a_margin(self):
        """Refuse to solve for a unit price when no unit price could work.

        Both divisors of the margin-to-price inversion are reachable with real
        orders: a line can be discounted to nothing, and a line can sit at zero
        quantity while its price is being negotiated. Neither has a unit price
        that produces a margin, so say so instead of dividing by zero.
        """
        self.check_singleton()
        if not self._get_margin_qty():
            raise UserError(
                self.env._(
                    "This line has no quantity, so no unit price can give it a"
                    " margin. Set the quantity first."
                )
            )
        if not self._get_discount_factor():
            raise UserError(
                self.env._(
                    "This line is discounted at 100%, so no unit price can give"
                    " it a margin. Lower the discount first."
                )
            )

    def _set_price_incl_taxes(self, price):
        """Assign `price_unit`, carrying whatever tax is included in the price.

        :param float price: the tax-excluded unit price that yields the margin.
        """
        self.check_singleton()
        details = self.tax_ids.flatten_taxes_hierarchy().compute_all(
            price, handle_price_include=False
        )
        included = sum(
            tax["amount"] for tax in details["taxes"] if tax["price_include"]
        )
        # Tax computation drifts on the last digits (100 comes back as
        # 100.0004), so land the result back on the currency.
        self.price_unit = self.currency_id.round(price + included)
