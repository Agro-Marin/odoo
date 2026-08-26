from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.fields import Command

#: How many historical lines the statistics block aggregates over. The block
#: reports `avg_sample_truncated` when the period holds more, so a capped
#: average is never read as the whole period.
STATS_SAMPLE_LIMIT = 500

#: How many historical lines the result list shows. The list is a shortlist,
#: not the history: `action_open_history` opens the full list/pivot/graph.
HISTORY_RESULT_LIMIT = 20


class MixinOrderLinePriceHistory(models.AbstractModel):
    _name = "mixin.order.line.price.history"
    _description = "Order Line Price History"

    #: Concrete order-line model the history is read from.
    _price_history_line_model = ""
    #: Action opened by `action_open_history`, as an xml id.
    _price_history_action = ""
    #: How the history is read, newest first. A line model that dates itself on
    #: another field overrides this rather than the two searches that use it.
    _price_history_order = "date_order desc, id desc"
    #: Stored column holding the discounted price per reference unit. It is
    #: what lets the extremes be a SQL MIN/MAX.
    _price_history_normalized_field = "price_unit_discounted_taxexc_product_uom"
    #: Whether the line model carries the three stored columns the grouped
    #: query needs -- `price_subtotal`, `product_uom_qty` and the normalized
    #: one above. A model without them is read row by row instead. Opting out
    #: is not only about missing columns: `account.move.line` has a subtotal
    #: and a quantity, but its quantity is in the line's own unit, so summing
    #: the pair across mixed units would answer confidently and wrongly.
    _price_history_sql = True

    period = fields.Selection(
        selection=[
            ("last_3m", "Last 3 Months"),
            ("last_12m", "Last 12 Months"),
            ("current_year", "Current Year"),
        ],
        default="last_12m",
        required=True,
        help="Period the statistics and the shortlist below are computed over.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
    )
    include_draft = fields.Boolean(
        string="Include Draft Documents",
        help="Add unconfirmed documents to the shortlist. Statistics always "
        "read confirmed documents only.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        compute="_compute_currency_id",
        store=True,
        precompute=True,
        readonly=False,
        help="Currency every price on this screen is normalized to.",
    )
    avg_price_unit = fields.Monetary(
        string="Average Price",
        compute="_compute_price_stats",
        currency_field="currency_id",
        help="Quantity-weighted average over confirmed documents in the "
        "period, all partners, target line excluded. Prices are normalized to "
        "the currency above and to the product reference unit of measure.",
    )
    min_price_unit = fields.Monetary(
        string="Lowest Price",
        compute="_compute_price_stats",
        currency_field="currency_id",
        help="Lowest normalized price in the period sample.",
    )
    max_price_unit = fields.Monetary(
        string="Highest Price",
        compute="_compute_price_stats",
        currency_field="currency_id",
        help="Highest normalized price in the period sample.",
    )
    avg_price_unit_exact = fields.Float(
        compute="_compute_price_stats",
        help="`avg_price_unit` before the currency rounds it. Every divergence "
        "on this screen divides by this one, so the wizard total and each row "
        "cannot disagree in the last decimal.",
    )
    avg_sample_count = fields.Integer(
        string="Sample Size",
        compute="_compute_price_stats",
    )
    partner_avg_price_unit = fields.Monetary(
        string="Average with this Partner",
        compute="_compute_price_stats",
        currency_field="currency_id",
        help="Quantity-weighted average over the same period, restricted to "
        "the selected partner and its commercial group. Read against the "
        "all-partner average beside it: that comparison, not the global figure "
        "alone, is what says whether this partner is priced with the market.",
    )
    partner_avg_sample_count = fields.Integer(
        string="Partner Sample Size",
        compute="_compute_price_stats",
    )
    partner_divergence_pct = fields.Float(
        string="Partner vs Market",
        compute="_compute_price_stats",
        help="Relative difference between the partner average and the "
        "all-partner average.",
    )
    partner_divergence_favorable = fields.Boolean(
        compute="_compute_price_stats",
    )
    avg_sample_truncated = fields.Boolean(
        compute="_compute_price_stats",
        help="The period holds more documents than the sample cap, so the "
        "statistics read the most recent ones only.",
    )
    current_price_unit = fields.Monetary(
        string="Current Price",
        compute="_compute_price_stats",
        currency_field="currency_id",
        help="Target line effective price, normalized like the average.",
    )
    divergence_pct = fields.Float(
        string="Divergence",
        compute="_compute_price_stats",
        help="Relative difference between the target line price and the "
        "period average.",
    )
    divergence_favorable = fields.Boolean(
        compute="_compute_price_stats",
        help="Whether the divergence goes the way this document type wants: "
        "below average when buying, above average when selling.",
    )

    def _get_price_direction(self) -> int:
        """``1`` when a higher price is favorable, ``-1`` when a lower one is."""
        return self.env[self._price_history_line_model]._price_direction

    @api.depends("line_id")
    def _compute_currency_id(self):
        for wizard in self:
            wizard.currency_id = (
                wizard.line_id.currency_id or wizard.env.company.currency_id
            )

    @api.depends("product_id", "period", "line_id", "currency_id")
    def _compute_price_stats(self):
        for wizard in self:
            wizard.update(wizard._get_price_stats())

    def _get_period_start(self):
        today = fields.Date.context_today(self)
        if self.period == "current_year":
            return today.replace(month=1, day=1)
        if self.period == "last_3m":
            return today - relativedelta(months=3)
        return today - relativedelta(months=12)

    def _get_price_sample(self, line) -> dict:
        """Raw comparison inputs read off one historical line."""
        return {
            "price": line.price_unit_discounted_taxexc,
            "qty": line.product_qty,
            "uom": line.product_uom_id,
            "currency": line.currency_id,
            "date": line.date_order and line.date_order.date(),
        }

    def _get_price_normalized(self, line) -> tuple[float, float]:
        """``line``'s discounted price and quantity in reference UoM and currency."""
        sample = self._get_price_sample(line)
        reference_uom = line.product_id.uom_id
        price = sample["uom"]._compute_price_report(sample["price"], reference_uom)
        qty = sample["uom"]._compute_quantity_estimate(
            sample["qty"], reference_uom, round=False
        )
        currency = sample["currency"]
        if currency and self.currency_id and currency != self.currency_id:
            price = currency._convert(
                price,
                self.currency_id,
                self.env.company,
                sample["date"] or fields.Date.context_today(self),
                round=False,
            )
        return price, qty

    def _get_domain_price_stats(self):
        if not self.product_id:
            return None
        return [
            ("product_id", "=", self.product_id.id),
            ("state", "=", "done"),
            ("date_order", ">=", self._get_period_start()),
            ("id", "not in", self.line_id.ids),
        ]

    def _get_price_stats(self) -> dict:
        self.ensure_one()
        vals = {
            "avg_price_unit": 0.0,
            "avg_price_unit_exact": 0.0,
            "min_price_unit": 0.0,
            "max_price_unit": 0.0,
            "avg_sample_count": 0,
            "avg_sample_truncated": False,
            "partner_avg_price_unit": 0.0,
            "partner_avg_sample_count": 0,
            "partner_divergence_pct": 0.0,
            "partner_divergence_favorable": False,
            "current_price_unit": 0.0,
            "divergence_pct": 0.0,
            "divergence_favorable": False,
        }
        domain = self._get_domain_price_stats()
        if domain:
            vals.update(self._get_price_aggregates(domain))
            vals.update(self._get_partner_price_aggregates(domain, vals))
        market = vals["avg_price_unit_exact"]
        if self.line_id:
            price, _qty = self._get_price_normalized(self.line_id)
            vals["current_price_unit"] = price
            if market:
                vals["divergence_pct"] = divergence = (price - market) / market
                vals["divergence_favorable"] = (
                    divergence * self._get_price_direction() > 0
                )
        return vals

    def _get_partner_price_aggregates(self, domain, market_vals) -> dict:
        """The same figures again, restricted to the selected partner.

        A second query rather than a second accumulator over the sample above:
        that sample is the most recent `STATS_SAMPLE_LIMIT` rows across all
        partners, so it can hold none of this partner's even when the partner
        has years of history, and an accumulator would answer "never bought
        from them" with a straight face.
        """
        if not self.partner_id:
            return {}
        partner_domain = [
            *domain,
            ("partner_id", "child_of", self.partner_id.commercial_partner_id.ids),
        ]
        partner_vals = self._get_price_aggregates(partner_domain)
        average = partner_vals.get("avg_price_unit_exact") or 0.0
        market = market_vals["avg_price_unit_exact"]
        result = {
            "partner_avg_price_unit": average,
            "partner_avg_sample_count": partner_vals.get("avg_sample_count", 0),
        }
        if average and market:
            divergence = (average - market) / market
            result["partner_divergence_pct"] = divergence
            result["partner_divergence_favorable"] = (
                divergence * self._get_price_direction() > 0
            )
        return result

    def _get_price_aggregates(self, domain) -> dict:
        """Weighted average, extremes and sample size over ``domain``.

        One grouped query when every matching line is already priced in the
        target currency, which is the ordinary case and has no sample cap.
        A mixed-currency sample cannot be aggregated in SQL -- each row
        converts at its own document date -- so that one falls back to
        :meth:`_get_price_sample_aggregates`, capped and reported as such.
        """
        if not self._price_history_sql:
            return self._get_price_sample_aggregates(domain)
        Line = self.env[self._price_history_line_model]
        groups = Line._read_group(
            domain,
            ["currency_id"],
            [
                "price_subtotal:sum",
                f"{self._price_history_normalized_field}:min",
                f"{self._price_history_normalized_field}:max",
                "product_uom_qty:sum",
                "__count",
            ],
        )
        if not groups:
            return {}
        if len(groups) > 1 or groups[0][0] != self.currency_id:
            return self._get_price_sample_aggregates(domain)
        _currency, amount, minimum, maximum, qty, count = groups[0]
        if not qty:
            return {}
        return {
            "avg_price_unit": amount / qty,
            "avg_price_unit_exact": amount / qty,
            "min_price_unit": minimum,
            "max_price_unit": maximum,
            "avg_sample_count": count,
            "avg_sample_truncated": False,
        }

    def _get_price_sample_aggregates(self, domain) -> dict:
        """The same figures read row by row, converting each at its own date."""
        lines = self.env[self._price_history_line_model].search(
            domain, order=self._price_history_order, limit=STATS_SAMPLE_LIMIT
        )
        total_amount = total_qty = 0.0
        count = 0
        min_price = max_price = None
        for line in lines:
            price, qty = self._get_price_normalized(line)
            if qty <= 0:
                continue
            total_amount += price * qty
            total_qty += qty
            count += 1
            min_price = price if min_price is None else min(min_price, price)
            max_price = price if max_price is None else max(max_price, price)
        if not total_qty:
            return {"avg_sample_truncated": len(lines) == STATS_SAMPLE_LIMIT}
        return {
            "avg_price_unit": total_amount / total_qty,
            "avg_price_unit_exact": total_amount / total_qty,
            "min_price_unit": min_price,
            "max_price_unit": max_price,
            "avg_sample_count": count,
            "avg_sample_truncated": len(lines) == STATS_SAMPLE_LIMIT,
        }

    def _get_domain_price_history(self):
        states = ["done", "draft"] if self.include_draft else ["done"]
        domain = [
            ("product_id", "=", self.product_id.id),
            ("state", "in", states),
            ("date_order", ">=", self._get_period_start()),
            ("id", "not in", self.line_id.ids),
        ]
        if self.partner_id:
            domain.append(
                ("partner_id", "child_of", self.partner_id.commercial_partner_id.ids)
            )
        return domain

    @api.onchange("partner_id", "product_id", "include_draft", "period")
    def _onchange_price_history_filters(self):
        self.line_ids = [Command.clear()]
        if not self.product_id:
            return
        lines = self.env[self._price_history_line_model].search(
            self._get_domain_price_history(),
            order=self._price_history_order,
            limit=HISTORY_RESULT_LIMIT,
        )
        self.line_ids = [Command.create({"line_id": line.id}) for line in lines]

    def _get_domain_price_confirmed(self):
        """What "this document really happened" means for the line model."""
        return [("state", "=", "done")]

    def action_open_history(self):
        """Leave the shortlist for the full list/pivot/graph history."""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            self._price_history_action,
        )
        domain = [
            ("product_id", "=", self.product_id.id),
            *self._get_domain_price_confirmed(),
        ]
        if self.partner_id:
            domain.append(
                ("partner_id", "child_of", self.partner_id.commercial_partner_id.ids)
            )
        action["domain"] = domain
        action["display_name"] = _("Price History for %s", self.product_id.display_name)
        return action


class MixinOrderLinePriceHistoryLine(models.AbstractModel):
    _name = "mixin.order.line.price.history.line"
    _description = "Order Line Price History Result"

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        help="Currency the normalized price is expressed in. Concrete models "
        "relate this to their wizard.",
    )
    price_unit_normalized = fields.Monetary(
        string="Normalized Price",
        compute="_compute_divergence",
        currency_field="currency_id",
        help="This line's discounted price, converted to the wizard currency "
        "and to the product reference unit of measure. This is the only "
        "column comparable across units and currencies.",
    )
    divergence_pct = fields.Float(
        string="vs Average",
        compute="_compute_divergence",
        help="Relative difference between this line's normalized price and "
        "the period average.",
    )
    divergence_favorable = fields.Boolean(
        compute="_compute_divergence",
    )

    @api.depends("line_id", "wizard_id.avg_price_unit_exact", "wizard_id.currency_id")
    def _compute_divergence(self):
        for record in self:
            wizard = record.wizard_id
            record.price_unit_normalized = 0.0
            record.divergence_pct = 0.0
            record.divergence_favorable = False
            if not record.line_id:
                continue
            price, _qty = wizard._get_price_normalized(record.line_id)
            record.price_unit_normalized = price
            market = wizard.avg_price_unit_exact
            if not market:
                continue
            divergence = (price - market) / market
            record.divergence_pct = divergence
            record.divergence_favorable = divergence * wizard._get_price_direction() > 0

    def _get_price_vals(self) -> dict:
        target = self.wizard_id.line_id
        return {
            "price_unit": self.line_id.product_uom_id._compute_price(
                self.price_unit, target.product_uom_id
            ),
            "discount": self.discount,
        }

    def action_set_price(self):
        self.ensure_one()
        self.wizard_id.line_id.write(self._get_price_vals())
        return {"type": "ir.actions.act_window_close"}
