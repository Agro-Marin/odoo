from collections import defaultdict
from datetime import date, datetime, time
from itertools import batched

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL

from odoo.addons.stock_account.models.avco import AvcoAccumulator
from odoo.addons.stock_account.models.constants import (
    COST_METHOD_SELECTION,
    VALUATION_SELECTION,
)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cost_method = fields.Selection(
        string="Cost Method",
        selection=COST_METHOD_SELECTION,
        compute="_compute_cost_method",
    )
    valuation = fields.Selection(
        string="Valuation",
        selection=VALUATION_SELECTION,
        compute="_compute_valuation",
        search="_search_valuation",
    )
    lot_valuated = fields.Boolean(
        string="Valuation by Lot/Serial",
        compute="_compute_lot_valuated",
        store=True,
        readonly=False,
        help="If checked, the valuation will be specific by Lot/Serial number.",
    )

    def _search_valuation(self, operator, value):
        if operator not in ("=", "!="):
            raise UserError(
                self.env._(
                    "You can only use the '=' and '!=' operators to search on valuation field."
                )
            )
        valuations = [key for key, _label in VALUATION_SELECTION]
        if value not in valuations:
            raise UserError(
                self.env._(
                    "Only the value 'periodic' and 'real_time' are accepted to search on valuation field."
                )
            )
        if operator == "!=":
            # The selection is binary, so "not periodic" is exactly "real_time".
            # Negating the value keeps a positive domain, which the company/category
            # fallback logic below relies on.
            value = next(v for v in valuations if v != value)
            operator = "="
        domain_categ = Domain([("categ_id.property_valuation", operator, value)])
        domain_company = Domain(
            [
                "|",
                ("categ_id.property_valuation", "=", False),
                ("categ_id", "=", False),
                ("company_id.inventory_valuation", operator, value),
            ]
        )
        if (
            self.env.company.inventory_valuation
            and self.env.company.inventory_valuation == value
        ):
            domain_company = Domain(
                [
                    "|",
                    ("categ_id.property_valuation", "=", False),
                    ("categ_id", "=", False),
                    "|",
                    ("company_id.inventory_valuation", operator, value),
                    ("company_id", "=", False),
                ]
            )
        return domain_company | domain_categ

    @api.depends("tracking")
    def _compute_lot_valuated(self):
        for product in self:
            if product.tracking == "none":
                product.lot_valuated = False

    @api.depends_context("company")
    @api.depends("categ_id.property_cost_method")
    def _compute_cost_method(self):
        for product_template in self:
            product_template.cost_method = (
                product_template.categ_id.with_company(
                    product_template.company_id
                ).property_cost_method
                or (product_template.company_id or self.env.company).cost_method
            )

    @api.depends_context("company")
    @api.depends("categ_id.property_valuation")
    def _compute_valuation(self):
        for product_template in self:
            product_template.valuation = (
                product_template.categ_id.with_company(
                    product_template.company_id
                ).property_valuation
                or self.env.company.inventory_valuation
            )

    def write(self, vals):
        product_ids_to_update = set()
        lot_ids_to_update = set()
        if "categ_id" in vals:
            category = self.env["product.category"].browse(vals["categ_id"])
            cost_method = (
                category.property_cost_method
                if category
                else self.env.company.cost_method
            )
            for product in self:
                if product.cost_method != cost_method:
                    product_ids_to_update.update(product.product_variant_ids.ids)

        if "lot_valuated" in vals:
            if vals.get("lot_valuated"):
                products_to_enable = self.filtered(lambda p: not p.lot_valuated)
                if products_to_enable:
                    problematic_quants = self.env["stock.quant"].search(
                        [
                            (
                                "product_id",
                                "in",
                                products_to_enable.product_variant_ids.ids,
                            ),
                            ("lot_id", "=", False),
                            ("quantity", "!=", 0),
                            ("location_id.is_valued_internal", "=", True),
                        ]
                    )
                    if problematic_quants:
                        raise UserError(
                            self.env._(
                                "You cannot enable lot valuation because the following products have"
                                " on-hand quantities without a lot/serial number:\n%s",
                                problematic_quants.product_id.mapped("display_name"),
                            )
                        )
            for product in self:
                if product.lot_valuated != vals.get(
                    "lot_valuated", product.lot_valuated
                ):
                    product_ids_to_update.update(product.product_variant_ids.ids)

        products_to_update = self.env["product.product"].browse(product_ids_to_update)
        lot_ids_to_update.update(
            self.env["stock.lot"]
            .sudo()
            .search(
                [
                    (
                        "product_id",
                        "in",
                        products_to_update.filtered(lambda p: p.lot_valuated).ids,
                    ),
                ]
            )
            .ids
        )

        res = super().write(vals)
        if "lot_valuated" in vals:
            lot_ids_to_update.update(
                self.env["stock.lot"]
                .sudo()
                .search(
                    [
                        ("product_id", "in", self.product_variant_ids.ids),
                    ]
                )
                .ids
            )
        if product_ids_to_update:
            self.env["product.product"].browse(
                product_ids_to_update
            )._update_standard_price()
        if lot_ids_to_update:
            self.env["stock.lot"].browse(
                lot_ids_to_update
            ).sudo()._update_standard_price()
        return res

    # -------------------------------------------------------------------------
    # Misc.
    # -------------------------------------------------------------------------

    def _get_product_accounts(self):
        """Add the stock accounts related to product to the result of super()
        @return: dictionary which contains information regarding stock accounts and super (income+expense accounts)
        """
        accounts = super()._get_product_accounts()
        accounts["stock_valuation"] = (
            self.categ_id.property_stock_valuation_account_id
            or self.categ_id._fields[
                "property_stock_valuation_account_id"
            ].get_company_dependent_fallback(self.categ_id)
            or self.env.company.account_stock_valuation_id
        )
        accounts["stock_variation"] = accounts[
            "stock_valuation"
        ].account_stock_variation_id
        return accounts

    def get_product_accounts(self, fiscal_pos=None):
        """Add the stock journal related to product to the result of super()
        @return: dictionary which contains all needed information regarding stock accounts and journal and super (income+expense accounts)
        """
        accounts = super().get_product_accounts(fiscal_pos=fiscal_pos)
        accounts.update(
            {
                "stock_journal": (
                    self.categ_id.property_stock_journal
                    or self.categ_id._fields[
                        "property_stock_journal"
                    ].get_company_dependent_fallback(self.categ_id)
                    or self.env.company.account_stock_journal_id
                )
            }
        )
        return accounts


class ProductProduct(models.Model):
    _inherit = "product.product"

    avg_cost = fields.Monetary(
        string="Average Cost",
        compute="_compute_value",
        compute_sudo=True,
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
        help="Technical field to correctly show the currently selected company's currency that corresponds "
        "to the totaled value of the product's valuation layers",
    )

    @api.depends_context("to_date", "company", "allowed_company_ids", "warehouse_id")
    @api.depends("cost_method", "stock_move_ids.value", "standard_price")
    def _compute_value(self):
        main_currency = self.env.company.currency_id
        self.company_currency_id = main_currency

        # A bare date (or 10-char date string) means "as of the end of that day";
        # a full datetime is honoured as-is. Keeps value consistent with the
        # quantity computation, which applies the same rule on the `to_date` context.
        original_value = self.env.context.get("to_date")
        at_date = fields.Datetime.to_datetime(original_value)
        if (
            isinstance(original_value, date)
            and not isinstance(original_value, datetime)
        ) or (isinstance(original_value, str) and len(original_value) == 10):
            at_date = datetime.combine(at_date.date(), time.max)

        # `compute_sudo=True` bypasses the company record rules, so the valuation cannot
        # rely on them to stay isolated per company. Value each selected company on its
        # own scope (own quantities/moves/prices), then aggregate converting every
        # company's value into the main company's currency (adapts odoo/odoo#270575).
        std_price_by_company_id = {}
        total_value_by_company_id = {}
        for company in self.env.companies:
            (
                std_price_by_company_id[company.id],
                total_value_by_company_id[company.id],
            ) = self._get_valuation_by_company(company, at_date)

        for product in self:
            product.total_value = sum(
                company.currency_id._convert(
                    total_value_by_company_id[company.id].get(product.id, 0),
                    main_currency,
                )
                for company in self.env.companies
            )
            product.avg_cost = std_price_by_company_id[self.env.company.id].get(
                product.id, product.standard_price
            )

    def _scoped_for_company(self, company, at_date=None):
        """``self`` narrowed to ``company``'s valuation scope: its valued locations,
        its owners, its company-dependent prices."""
        products = self.with_company(company).with_context(
            allowed_company_ids=company.ids
        )
        products = products._with_valuation_context()
        if at_date:
            products = products.with_context(at_date=at_date, to_date=at_date)
        return products

    def _get_valuation_by_company(self, company, at_date=None):
        """``(unit_cost_by_product_id, value_by_product_id)`` for ``company`` alone,
        expressed in ``company``'s own currency.

        ``total_value`` deliberately aggregates every company in ``env.companies``,
        so it is the wrong numerator for anything that divides by a *single*
        company's quantity -- a quant's share of its product, a one-company
        closing. Those callers ask for a company explicitly, through here.
        """
        return self._scoped_for_company(company, at_date)._run_valuation_batches(
            at_date
        )

    def _run_valuation_batches(self, at_date=None):
        """Value the products in ``self`` -- which must already carry a valuation
        context/scope, see ``_scoped_for_company`` -- and return
        ``(std_price_by_product_id, total_value_by_product_id)``, the total value having
        the warehouse ratio already applied."""
        # PERF: Pre-compute:the sum of 'total_value' of lots per product in go
        std_price_by_product_id = {}
        total_value_by_product_id = {}
        lot_valuated_products_ids = {p.id for p in self if p.lot_valuated}
        if lot_valuated_products_ids:
            # Scope the lots to the company being valued: this runs under
            # `compute_sudo=True`, so the `stock.lot` record rule is bypassed and
            # the `product_qty != 0` clause below -- which is dropped whenever
            # `at_date` or `warehouse_id` is set -- is the only other thing that
            # would have kept another company's lots out of the sum.
            domain = Domain(
                [
                    ("product_id", "in", lot_valuated_products_ids),
                    ("company_id", "in", [*self.env.company.ids, False]),
                ]
            )
            if not at_date and not self.env.context.get("warehouse_id"):
                domain &= Domain([("product_qty", "!=", 0)])
            lots_by_product = self.env["stock.lot"]._read_group(
                domain, groupby=["product_id"], aggregates=["id:recordset"]
            )
            # Collect all lots and trigger batch computation of total_value
            self.env["stock.lot"].browse(
                lot.id for _, lots in lots_by_product for lot in lots
            ).mapped("total_value")
            for product, lots in lots_by_product:
                value = sum(lots.mapped("total_value"))
                qty = product.qty_available
                std_price_by_product_id[product.id] = (
                    value / qty
                    if not product.uom_id.is_zero(qty)
                    else product.standard_price
                )
                total_value_by_product_id[product.id] = value

        product_ids_grouped_by_cost_method = defaultdict(set)
        ratio_by_product_id = {}
        for product in self:
            if product.lot_valuated:
                continue
            product_whole_company_context = product.with_context(warehouse_id=False)
            # A negative owned on-hand that is fully offset by non-owned consignment
            # stock is not a real oversold position: it has no cost basis, so value it
            # like an empty valued quantity instead of `qty * standard_price`.
            if product.uom_id.is_zero(product.qty_available) or (
                product.uom_id.compare(product.qty_available, 0) < 0
                and product._is_negative_owned_offset_by_consignment(at_date)
            ):
                total_value_by_product_id[product.id] = 0
                std_price_by_product_id[product.id] = product.standard_price
                continue
            if product.uom_id.is_zero(product_whole_company_context.qty_available):
                total_value_by_product_id[product.id] = (
                    product.standard_price * product.qty_available
                )
                std_price_by_product_id[product.id] = product.standard_price
                continue
            if (
                product.uom_id.compare(
                    product.qty_available, product_whole_company_context.qty_available
                )
                != 0
            ):
                ratio = (
                    product.qty_available / product_whole_company_context.qty_available
                )
                ratio_by_product_id[product.id] = ratio

            if product.cost_method == "standard":
                product_ids_grouped_by_cost_method["standard"].add(product.id)
            elif product.cost_method == "average":
                product_ids_grouped_by_cost_method["average"].add(product.id)
            else:
                product_ids_grouped_by_cost_method["fifo"].add(product.id)

        for cost_method, product_ids in product_ids_grouped_by_cost_method.items():
            valued_products = (
                self.env["product.product"]
                .browse(product_ids)
                .with_context(warehouse_id=False)
            )
            # To remove once price_unit isn't truncate in sql anymore (no need of force_recompute)
            if cost_method == "standard":
                std_prices, total_values = valued_products._run_standard_batch(
                    at_date=at_date
                )
            elif cost_method == "average":
                std_prices, total_values = valued_products._run_average_batch(
                    at_date=at_date, force_recompute=True
                )
            else:
                std_prices, total_values = valued_products._run_fifo_batch(
                    at_date=at_date
                )

            std_price_by_product_id.update(std_prices)
            for product_id, total_value in total_values.items():
                total_value_by_product_id[product_id] = (
                    total_value * ratio_by_product_id.get(product_id, 1)
                )

        return std_price_by_product_id, total_value_by_product_id

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        # naive sentinel valuation_date: compared against Odoo's naive ORM dates
        products.with_context(
            valuation_date=datetime.min  # noqa: DTZ901
        )._change_standard_price(
            {product: 0 for product in products if product.standard_price}
        )
        return products

    def write(self, vals):
        old_price = False
        if "standard_price" in vals and not self.env.context.get(
            "disable_auto_revaluation"
        ):
            old_price = {product: product.standard_price for product in self}
        if "lot_valuated" in vals:
            # lot_valuated must be updated from the ProductTemplate
            self.product_tmpl_id.write({"lot_valuated": vals.pop("lot_valuated")})
        res = super().write(vals)
        if old_price:
            self._change_standard_price(old_price)
        return res

    # -------------------------------------------------------------------------
    # Private
    # -------------------------------------------------------------------------

    def _change_standard_price(self, old_price):
        product_values = []
        product_ids_lot_valuated = set()
        date = self.env.context.get("valuation_date") or fields.Datetime.now()
        for product in self:
            # Default the previous price to 0 (the field default) so that a product
            # created at a 0 standard price does not record a spurious "0 -> 0" history
            # row. Such a row (dated datetime.min) otherwise seeds `_run_average_batch`
            # with an average cost of 0 and poisons the valuation of out-only lots.
            product_old_price = old_price.get(product, 0)
            if (
                product.cost_method == "fifo"
                or product.standard_price == product_old_price
            ):
                continue

            if product.lot_valuated:
                product_ids_lot_valuated.add(product.id)

            product_values.append(
                {
                    "product_id": product.id,
                    "value": product.standard_price,
                    # `standard_price` is company-dependent, so the value that just
                    # changed belongs to `env.company`. Stamping `product.company_id`
                    # instead filed a parent company's price change under a child,
                    # where `_get_last_product_value` -- which filters on
                    # `company_id = env.company.id` -- could never find it again.
                    "company_id": self.env.company.id,
                    "date": date,
                    "description": _(
                        "Price update from %(old_price)s to %(new_price)s by %(user)s",
                        old_price=product_old_price,
                        new_price=product.standard_price,
                        user=self.env.user.name,
                    ),
                }
            )
        # These rows record a price the caller has just written, so they must not
        # trigger the revaluation recompute in `product.value.create`.
        self.env["product.value"].sudo().with_context(
            disable_auto_revaluation=True
        ).create(product_values)
        if product_ids_lot_valuated:
            for product, lots in self.env["stock.lot"]._read_group(
                [("product_id", "in", product_ids_lot_valuated)],
                ["product_id"],
                ["id:recordset"],
            ):
                lots.with_context(
                    disable_auto_revaluation=True
                ).standard_price = product.standard_price

    def _get_standard_price_at_date(self, date=None):
        """Get Last Price History"""
        self.ensure_one()
        if not date or date == fields.Date.today():
            return self.standard_price
        if self.cost_method != "standard":
            raise ValidationError(
                _(
                    "You can only get the standard price at a given date for products with 'Standard Price' as cost method."
                )
            )
        product_value = self._get_last_product_value(date).get(self)
        return product_value.value if product_value else self.standard_price

    def _get_last_product_value(self, date=None, lot=False):
        # Scope to the current company explicitly: the query below runs sudo, which
        # bypasses `stock_account.product_value_rule`, so without this filter the
        # globally-latest manual revaluation of a company-shared product would seed
        # another company's valuation. Same reasoning as `_get_last_in`.
        domain = Domain(
            [
                ("product_id", "in", self.ids),
                ("move_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ]
        )
        if lot:
            domain &= Domain(["|", ("lot_id", "=", lot.id), ("lot_id", "=", False)])
        else:
            domain &= Domain([("lot_id", "=", False)])
        if date:
            domain &= Domain([("date", "<=", date)])

        product_values = self._read_latest_product_values(
            domain, SQL("product_value.product_id")
        )
        return {pv.product_id: pv for pv in product_values}

    def _read_latest_product_values(self, domain, group):
        """Latest `product.value` per `group` (an SQL column list), newest date then
        newest id winning."""
        query = self.env["product.value"].sudo()._search(domain)
        query.order = SQL("%s, product_value.date DESC, product_value.id DESC", group)
        query._ids = tuple(
            id_
            for (id_,) in self.env.execute_query(
                query.select(SQL("distinct ON (%s) product_value.id", group))
            )
        )
        product_values = self.env["product.value"].browse(query._ids)
        product_values.sudo().fetch(["product_id", "lot_id", "value", "date"])
        return product_values

    def _get_last_lot_values(self, lots, date=None):
        """Latest manual revaluation applying to each lot of `lots`: the lot's own
        `product.value` if it has one, otherwise the product-wide one.

        Two queries for the whole set, where reading them lot by lot (through
        `_get_last_product_value(lot=...)`) costs two per lot.

        :return: ``{lot: product.value}``, absent for lots with no applicable value.
        """
        base = Domain(
            [
                ("product_id", "in", self.ids),
                ("move_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ]
        )
        if date:
            base &= Domain([("date", "<=", date)])

        by_lot = {
            pv.lot_id: pv
            for pv in self._read_latest_product_values(
                base & Domain([("lot_id", "in", lots.ids)]),
                SQL("product_value.product_id, product_value.lot_id"),
            )
        }
        by_product = {
            pv.product_id: pv
            for pv in self._read_latest_product_values(
                base & Domain([("lot_id", "=", False)]),
                SQL("product_value.product_id"),
            )
        }

        values_by_lot = {}
        for lot in lots:
            candidates = [
                pv
                for pv in (by_lot.get(lot), by_product.get(lot.product_id))
                if pv is not None
            ]
            if candidates:
                # Same tiebreak as the single-lot query: newest date, then newest id.
                values_by_lot[lot] = max(candidates, key=lambda pv: (pv.date, pv.id))
        return values_by_lot

    def _get_last_in(self, date=None):
        # Scope to the current company explicitly: this runs from sudo call-sites
        # (compute_sudo valuation, _update_standard_price) where record rules are
        # bypassed, so without this filter the globally-latest in-move of another
        # company would leak into this company's standard price / historical value.
        last_in_domain = Domain(
            [
                ("is_in", "=", True),
                ("product_id", "=", self.id),
                ("company_id", "=", self.env.company.id),
            ]
        )
        if date:
            last_in_domain &= Domain([("date", "<=", date)])
        return self.env["stock.move"].search(
            last_in_domain, order="date desc, id desc", limit=1
        )

    def _is_negative_owned_offset_by_consignment(self, at_date=None):
        """Whether the product's negative owned on-hand is fully covered by non-owned
        consignment stock in the valuation scope, i.e. there is no real short position
        to value (vs. a genuine oversold position, which must be valued negatively).

        Read straight from quants to bypass the owner-insensitive ``qty_available``
        cache; only meaningful at the current date, hence skipped when ``at_date`` is
        set (a historical short position is valued normally)."""
        self.ensure_one()
        if at_date:
            return False
        # Same location/warehouse scope as qty_available, but without the owner filter.
        domain = (
            Domain([("product_id", "=", self.id)])
            & self.env["stock.location"]._quantity_domains_from_context()[0]
        )
        physical_qty = sum(
            self.env["stock.quant"].sudo().search(domain).mapped("quantity")
        )
        return self.uom_id.compare(physical_qty, 0) >= 0

    def _with_valuation_context(self):
        # Scope valued locations to `env.company` -- the company being valued -- and
        # NOT to `env.companies` (the set the user happens to have enabled in the
        # session switcher). Valuation is computed sudo (compute_sudo=True), which
        # bypasses the company record rules, so this filter is the only thing keeping
        # quantities from leaking across companies; widening it to `env.companies`
        # makes every derived figure (FIFO stack size, average cost, COGS) depend on
        # the session rather than on the data. The `owners` scope below is already
        # single-company for the same reason.
        if self.env.context.get("valuation_scope_company_id") == self.env.company.id:
            # Already scoped to this company. The scope depends on the company alone,
            # never on the product, so re-deriving it would repeat the location search
            # for every product of a loop.
            return self
        valued_locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search(
                [
                    ("is_valued_internal", "=", True),
                    ("company_id", "in", [*self.env.company.ids, False]),
                ]
            )
        )
        return self.with_context(
            valuation_scope_company_id=self.env.company.id,
            location=valued_locations.ids,
            owners=[False, self.env.company.partner_id.id],
            strict=True,
        )

    def _get_remaining_moves(self):
        moves_qty_by_product = {}
        # Scope once for the whole set: `_run_fifo_get_stack` re-scopes per product,
        # and that lookup is company-wide.
        for product in self._with_valuation_context():
            moves, remaining_qty = product._run_fifo_get_stack()
            moves = self.env["stock.move"].concat(*moves)
            if not moves:
                continue
            # `_get_valued_qty()`, not `quantity`: the bottom-of-stack figure below
            # comes from `_run_fifo_get_stack` in the product's UoM, so reading the
            # rest in the *move's* UoM put two units of measure in one mapping. A
            # receipt of one "Pack of 6" then reported 1 remaining where its
            # neighbour reported 6, and `_compute_remaining_value` divided one by
            # the other.
            qty_by_move = {m: m._get_valued_qty() for m in moves[1:]}
            qty_by_move[moves[0]] = remaining_qty
            moves_qty_by_product[product] = qty_by_move
        return moves_qty_by_product

    def _run_standard_batch(self, at_date=None, lot=None):
        std_price_by_product_id = {
            product.id: product.standard_price for product in self
        }
        if at_date:
            product_value_by_product = self._get_last_product_value(at_date, lot=lot)
            std_price_by_product_id = {
                product.id: product_value_by_product[product].value
                if product in product_value_by_product
                else product.standard_price
                for product in self
            }
        value_by_product_id = {
            p.id: p.qty_available * std_price_by_product_id.get(p.id, 0) for p in self
        }
        return std_price_by_product_id, value_by_product_id

    def _run_average_batch(self, at_date=None, lots=None, force_recompute=False):
        """Replay the AVCO recurrence over the moves of the products in `self`.

        :param lots: when set, value each of these `stock.lot` records separately
            instead of their products, in the same single pass over the moves. The
            returned mappings are then keyed by `stock.lot` id.
        :return: ``(unit_cost_by_key, value_by_key)``, keyed by `product.product`
            id, or by `stock.lot` id when `lots` is set.
        """
        lots = lots or self.env["stock.lot"]
        std_price_by_key = {}
        value_by_key = {}
        quantity_by_key = {}
        date_by_key = {}

        if not at_date and not force_recompute:
            std_price_by_key = {p.id: p.standard_price for p in self}
            value_by_key = {
                p.id: p.qty_available * std_price_by_key.get(p.id, 0) for p in self
            }
            return std_price_by_key, value_by_key

        moves_domain = Domain(
            [
                ("product_id", "in", self._as_query()),
                ("company_id", "=", self.env.company.id),
                "|",
                "|",
                ("is_in", "=", True),
                ("is_dropship", "=", True),
                ("is_out", "=", True),
            ]
        )
        if lots:
            moves_domain &= Domain(
                [
                    ("move_line_ids.lot_id", "in", lots.ids),
                ]
            )
        if at_date:
            moves_domain &= Domain(
                [
                    ("date", "<=", at_date),
                ]
            )

        # Seed each key from the latest manual revaluation that applies to it. The
        # quantity is read as of that revaluation's date, so keys sharing a date are
        # prefetched together rather than read one by one.
        if lots:
            manual_value_by_target = self._get_last_lot_values(lots, at_date)
        else:
            manual_value_by_target = self._get_last_product_value(at_date)
        target_ids_by_manual_value_date = defaultdict(list)
        for target, manual_value in manual_value_by_target.items():
            target_ids_by_manual_value_date[manual_value.date].append(target.id)

        for target, manual_value in manual_value_by_target.items():
            prefetched = target.with_prefetch(
                target_ids_by_manual_value_date[manual_value.date]
            )
            if lots:
                quantity = prefetched.with_context(
                    to_date=manual_value.date, skip_in_progress=True
                ).product_qty
            else:
                quantity = prefetched.with_context(
                    to_date=manual_value.date
                ).qty_available

            std_price_by_key[target.id] = manual_value.value
            quantity_by_key[target.id] = quantity
            value_by_key[target.id] = manual_value.value * quantity
            date_by_key[target.id] = manual_value.date

        # The floor below is a single global filter, so it is only safe when every
        # key starts from a revaluation: a key with none must replay from the very
        # first move.
        seeded_all = len(manual_value_by_target) == len(lots or self)
        oldest_manual_value = min(
            (pv.date for pv in manual_value_by_target.values()), default=False
        )
        if oldest_manual_value and seeded_all:
            moves_domain &= Domain([("date", ">=", oldest_manual_value)])

        self.env[
            "product.value"
        ].invalidate_model()  # Avoid keeping too many records in cache

        moves = self.env["stock.move"].search_fetch(
            moves_domain, field_names=["id"], order="product_id, date, id"
        )
        # PERF avoid memoryerror
        move_fields = [
            "date",
            "is_dropship",
            "is_in",
            "is_out",
            "location_dest_id",
            "location_id",
            "move_line_ids",
            "picked",
            "value",
            "product_id",
        ]
        move_line_fields = [
            "company_id",
            "location_id",
            "location_dest_id",
            "lot_id",
            "owner_id",
            "picked",
            "quantity_product_uom",
        ]

        batch_size = 50000

        # Walk every product's moves in one pass rather than one pass per product.
        # `moves` is ordered by (product_id, date, id), so a product's moves stay
        # contiguous and the recurrence is unchanged -- but the fetches below
        # batch across products instead of issuing a full round of queries (moves,
        # move lines, and each of their fields) per product, which is what made
        # valuing a catalogue cost a constant number of queries per product.
        #
        # There used to be a pre-pass here that fetched `product_id` and `date` for
        # every move just to drop the ones at or before the product's earliest
        # replay date. The loop below re-applies that test per key
        # (`date_by_key`), and the per-product floor was either the same value
        # (no lots) or the minimum across a product's lots -- never later than any
        # per-lot floor -- so the pre-pass could not drop a move this loop keeps.
        # With no manual revaluation at all it dropped nothing whatsoever and was
        # a second full scan of every move.
        avco_by_key = {}
        # Limit the memory usage since it's possible to have millions of stock.move
        for moves_batch in batched(moves.ids, batch_size, strict=False):
            moves_batch = self.env["stock.move"].browse(moves_batch)
            moves_batch.fetch(move_fields)
            moves_batch.move_line_ids.fetch(move_line_fields)
            for move in moves_batch:
                product = move.product_id
                # One target per key this move contributes to: the lots it carries
                # when valuing lots, the product itself otherwise. Both are
                # recordsets, so the body below is shared.
                for target in (move.move_line_ids.lot_id & lots) if lots else product:
                    target_lot = target if lots else None
                    key = target.id
                    valuation_from_date = date_by_key.get(key)
                    if valuation_from_date and move.date <= valuation_from_date:
                        continue
                    avco = avco_by_key.get(key)
                    if avco is None:
                        # Seed from this key's first surviving move: without a manual
                        # revaluation to start from, its unit price is the opening
                        # cost. The whole-move unit price is also the lot's, since a
                        # lot's share is prorated from that same value and quantity.
                        move_qty = move._get_valued_qty()
                        # For a valuation at date, a move must count for the value it
                        # had at that date (bills/rates that arrived later are
                        # excluded by `_get_value`), not for its stored value.
                        move_value = (
                            move._get_value(at_date=at_date) if at_date else move.value
                        )
                        avco = avco_by_key[key] = AvcoAccumulator(
                            quantity_by_key.get(key, 0),
                            value_by_key.get(key, 0),
                            std_price_by_key.get(
                                key, move_value / move_qty if move_qty else 0
                            ),
                            uom=product.uom_id,
                        )
                    if move.is_in or move.is_dropship:
                        in_qty = move._get_valued_qty()
                        in_value = (
                            move._get_value(at_date=at_date) if at_date else move.value
                        )
                        if move.is_dropship:
                            in_value = move._get_value(
                                forced_std_price=avco.unit_cost, at_date=at_date
                            )
                        if target_lot:
                            lot_qty = move._get_valued_qty(target_lot)
                            in_value = (in_value * lot_qty / in_qty) if in_qty else 0
                            in_qty = lot_qty
                        avco.add_in(in_qty, in_value)
                    if move.is_out or move.is_dropship:
                        out_qty = (
                            move._get_valued_qty(target_lot)
                            if target_lot
                            else move._get_valued_qty()
                        )
                        avco.add_out(out_qty)

            self.env[
                "stock.move"
            ].invalidate_model()  # Avoid keeping too many records in cache
            self.env["stock.move.line"].invalidate_model()

        for key, avco in avco_by_key.items():
            std_price_by_key[key] = avco.unit_cost
            value_by_key[key] = avco.value

        return std_price_by_key, value_by_key

    def _run_fifo_batch(self, at_date=None, lot=None, location=None):
        """Value the FIFO stack of the products in `self`.

        :param lot: when set, value that `stock.lot` instead of the product. The
            returned mappings are then keyed by `stock.lot` id, as in
            `_run_average_batch` -- keying a lot's figures by its product's id
            invites the caller to read another key's value.
        :return: ``(unit_cost_by_key, value_by_key)``.
        """
        std_price_by_key = {}
        value_by_key = {}
        for product in self:
            key = lot.id if lot else product.id
            quantity = lot.product_qty if lot else product.qty_available
            value = product._run_fifo(quantity, lot, at_date, location)
            if product.uom_id.is_zero(quantity):
                # Nothing to divide by. Keep the existing cost basis rather than
                # publishing a 0: `_run_standard_batch` falls back to
                # `standard_price` and the AVCO accumulator leaves `unit_cost`
                # untouched, so a 0 here made an emptied FIFO lot the only one of
                # the three to forget what it cost.
                std_price = lot.standard_price if lot else product.standard_price
            else:
                std_price = value / quantity
            std_price_by_key[key] = std_price
            value_by_key[key] = value

        return std_price_by_key, value_by_key

    def _run_fifo(self, quantity, lot=None, at_date=None, location=None):
        """Returns the value for the next outgoing product base on the qty give as argument."""
        self.ensure_one()
        if self.uom_id.compare(quantity, 0) <= 0:
            std_price = lot.standard_price if lot else self.standard_price
            if at_date:
                last_in = self._get_last_in(at_date)
                return quantity * (last_in._get_price_unit() if last_in else std_price)
            return quantity * std_price

        fifo_cost = 0
        fifo_stack, qty_on_first_move = self._run_fifo_get_stack(
            lot=lot, at_date=at_date, location=location
        )
        last_move = False
        # Going up to get the quantity in the argument
        while quantity > 0 and fifo_stack:
            move = fifo_stack.pop(0)
            last_move = move
            # At a date, value the move as it was known then (later bills or
            # rates are excluded by `_get_value`), not at its current value.
            move_value = move._get_value(at_date=at_date) if at_date else move.value
            if qty_on_first_move:
                valued_qty = move._get_valued_qty()
                in_qty = qty_on_first_move
                in_value = move_value * in_qty / valued_qty
                qty_on_first_move = 0
            else:
                in_qty = move._get_valued_qty()
                in_value = move_value
            if in_qty > quantity:
                in_value = in_value * quantity / in_qty
                in_qty = quantity
            fifo_cost += in_value
            quantity -= in_qty
        # When we required more quantity than available we extrapolate with the last known price
        if quantity > 0:
            # Derive the unit price from the valued quantity (product UoM), consistent
            # with `last_move.value`; `last_move.quantity` is in the move UoM and would
            # give a wrong unit price whenever the two UoMs differ (e.g. secondary UoM).
            last_move_valued_qty = last_move._get_valued_qty() if last_move else 0
            if last_move and last_move_valued_qty:
                last_move_value = (
                    last_move._get_value(at_date=at_date)
                    if at_date
                    else last_move.value
                )
                fifo_cost += quantity * (last_move_value / last_move_valued_qty)
            else:
                fifo_cost += quantity * self.standard_price
        return fifo_cost

    def _run_fifo_get_stack(self, lot=None, at_date=None, location=None):
        # TODO: return a list of tuple (move, valued_qty) instead
        external_location = location and location.is_valued_external
        fifo_stack = []
        fifo_stack_size = 0
        if location:
            self = self.with_context(location=location.ids)
        if lot:
            fifo_stack_size = lot.product_qty
        elif location:
            # Keep the explicit `location` scope: `_with_valuation_context` would
            # override it with every valued location, mismatching the location-only
            # `moves_domain` below and mis-sizing the stack.
            fifo_stack_size = self.with_context(to_date=at_date).qty_available
        else:
            fifo_stack_size = (
                self._with_valuation_context()
                .with_context(to_date=at_date)
                .qty_available
            )
        if self.env.context.get("fifo_qty_already_processed"):
            # When validating multiple moves at the same time, the qty_available won't be up to date yet
            fifo_stack_size -= self.env.context["fifo_qty_already_processed"]
        if self.uom_id.compare(fifo_stack_size, 0) <= 0:
            return fifo_stack, 0

        moves_domain = Domain(
            [
                ("product_id", "=", self.id),
                ("company_id", "=", self.env.company.id),
            ]
        )
        if lot:
            moves_domain &= Domain([("move_line_ids.lot_id", "in", lot.id)])
        if at_date:
            moves_domain &= Domain([("date", "<=", at_date)])
        if location:
            moves_domain &= Domain([("location_dest_id", "=", location.id)])
        if external_location:
            moves_domain &= Domain([("is_out", "=", True)])
        else:
            moves_domain &= Domain([("is_in", "=", True)])

        # Arbitrary limit as we can't guess how many moves correspond to the qty_available, but avoid fetching all moves at the same time.
        initial_limit = 100
        moves_in = self.env["stock.move"].search(
            moves_domain, order="date desc, id desc", limit=initial_limit
        )

        remaining_qty_on_first_stack_move = 0
        current_offset = 0
        # Go to the bottom of the stack
        while self.uom_id.compare(fifo_stack_size, 0) > 0 and moves_in:
            move = moves_in[0]
            moves_in = moves_in[1:]
            in_qty = move._get_valued_qty()
            fifo_stack.append(move)
            remaining_qty_on_first_stack_move = min(in_qty, fifo_stack_size)
            fifo_stack_size -= in_qty
            if self.uom_id.compare(fifo_stack_size, 0) > 0 and not moves_in:
                # We need to fetch more moves
                current_offset += 1
                moves_in = self.env["stock.move"].search(
                    moves_domain,
                    order="date desc, id desc",
                    offset=current_offset * initial_limit,
                    limit=initial_limit,
                )
        fifo_stack.reverse()
        return fifo_stack, remaining_qty_on_first_stack_move

    def _update_standard_price(self, extra_value=None, extra_quantity=None):
        """Update the standard price of product in self.
        :params extra_value dict: Additional value by product in case of in move in order to simply recompute
        standard price base old quantity * standard price + extra_value / total quantity available
        :params extra_quantity dict: Added quantity to the quantity available used to recompute the previous
        quantity for the computation defined in extra_value params.
        """
        products_by_cost_method = defaultdict(set)
        for product in self:
            if product.lot_valuated and product.cost_method != "standard":
                product.sudo().with_context(
                    disable_auto_revaluation=True
                ).standard_price = product.avg_cost
                continue
            products_by_cost_method[product.cost_method].add(product.id)
        for cost_method, product_ids in products_by_cost_method.items():
            # The valuation terms are computed in sudo (compute_sudo=True) and are thus
            # unrestricted, while `qty_available` follows the user's record rules (e.g.
            # a rule restricting access to specific warehouses/locations). Pairing an
            # unrestricted value with a partial `qty_available` yields an aberrant
            # standard price, so run the whole update in sudo to keep both terms on the
            # same scope. See odoo/odoo#270559.
            products = self.env["product.product"].sudo().browse(product_ids)
            if cost_method == "standard":
                continue

            if extra_value is not None and extra_quantity is not None:
                products_with_incremental_recompute = (
                    (self.env["product.product"].concat(*extra_value.keys()) & products)
                    .sudo()
                    .with_context(allowed_company_ids=self.env.company.ids)
                    ._with_valuation_context()
                )
                products_with_incremental_recompute.fetch(["qty_available"])
                for product in products_with_incremental_recompute:
                    added_value = extra_value.get(product)
                    added_qty = extra_quantity.get(product)
                    previous_qty = product.qty_available - added_qty
                    if (
                        product.uom_id.compare(previous_qty, 0) > 0
                        and product.uom_id.compare(product.qty_available, 0) > 0
                    ):
                        new_avg_cost = (
                            previous_qty * product.standard_price + added_value
                        ) / product.qty_available
                    else:
                        new_avg_cost = added_value / added_qty
                    product.with_context(
                        disable_auto_revaluation=True
                    ).sudo().standard_price = new_avg_cost
                products -= products_with_incremental_recompute

            if cost_method == "fifo":
                # Scope once for the whole set rather than per product: the scope is
                # company-wide, and `_run_fifo` re-derives it further down.
                for product in products._with_valuation_context():
                    qty_available = product.qty_available
                    if product.uom_id.compare(qty_available, 0) > 0:
                        # Value the stack directly rather than reading `total_value`:
                        # that field is deliberately a cross-company aggregate (see
                        # `_compute_value`), and dividing it by a single company's
                        # quantity to feed the company-dependent `standard_price`
                        # blends the companies' costs together.
                        product.sudo().with_context(
                            disable_auto_revaluation=True
                        ).standard_price = (
                            product._run_fifo(qty_available) / qty_available
                        )
                    elif last_in := product._get_last_in():
                        if last_in_price_unit := last_in._get_price_unit():
                            product.sudo().with_context(
                                disable_auto_revaluation=True
                            ).standard_price = last_in_price_unit

            elif cost_method == "average":
                new_standard_price_by_product = products._run_average_batch(
                    force_recompute=True
                )[0]
                for product in products:
                    if product.id in new_standard_price_by_product:
                        product.with_context(
                            disable_auto_revaluation=True
                        ).sudo().standard_price = new_standard_price_by_product[
                            product.id
                        ]


class ProductCategory(models.Model):
    _inherit = "product.category"

    anglo_saxon_accounting = fields.Boolean(
        string="Use Anglo-Saxon Accounting",
        compute="_compute_anglo_saxon_accounting",
        help="If checked, the product will be valued using the Anglo-Saxon accounting method.",
    )
    property_valuation = fields.Selection(
        string="Inventory Valuation",
        selection=VALUATION_SELECTION,
        company_dependent=True,
        copy=True,
        tracking=True,
        help="""Periodic: The accounting entries are suggested manually in the inventory valuation report.
        Perpetual: An accounting entry is automatically created to value the inventory when a product is billed or invoiced.
        """,
    )
    property_cost_method = fields.Selection(
        string="Costing Method",
        selection=COST_METHOD_SELECTION,
        company_dependent=True,
        copy=True,
        default=lambda self: self.env.company.cost_method,
        help="""Standard Price: The products are valued at their standard cost defined on the product.
        Average Cost (AVCO): The products are valued at weighted average cost.
        First In First Out (FIFO): The products are valued supposing those that enter the company first will also leave it first.
        """,
        tracking=True,
    )
    property_stock_journal = fields.Many2one(
        "account.journal",
        "Stock Journal",
        company_dependent=True,
        help="When doing automated inventory valuation, this is the Accounting Journal in which entries will be automatically posted when stock moves are processed.",
    )
    property_stock_valuation_account_id = fields.Many2one(
        "account.account",
        "Stock Valuation Account",
        company_dependent=True,
        ondelete="restrict",
        check_company=True,
        help="""When automated inventory valuation is enabled on a product, this account will hold the current value of the products.""",
    )
    property_price_difference_account_id = fields.Many2one(
        "account.account",
        "Price Difference Account",
        company_dependent=True,
        ondelete="restrict",
        check_company=True,
        help="""With perpetual valuation, this account will hold the price difference between the standard price and the bill price.""",
    )
    account_stock_variation_id = fields.Many2one(
        "account.account",
        string="Stock Variation Account",
        readonly=False,
        related="property_stock_valuation_account_id.account_stock_variation_id",
    )

    @api.depends_context("company")
    def _compute_anglo_saxon_accounting(self):
        self.anglo_saxon_accounting = self.env.company.anglo_saxon_accounting

    def write(self, vals):
        products_to_update = self.env["product.product"]
        if "property_cost_method" in vals:
            updated_categories = self.filtered(
                lambda c: c.property_cost_method != vals["property_cost_method"]
            )
            if updated_categories:
                products_to_update = self.env["product.product"].search(
                    [("categ_id", "in", updated_categories.ids)]
                )
        res = super().write(vals)
        if products_to_update:
            products_to_update._update_standard_price()
        products_lot_valuated = products_to_update.filtered(lambda p: p.lot_valuated)
        if products_lot_valuated:
            self.env["stock.lot"].sudo().search(
                [("product_id", "in", products_lot_valuated.ids)]
            )._update_standard_price()
        return res
