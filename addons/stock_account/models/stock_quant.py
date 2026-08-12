# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.tools.misc import groupby

from odoo.addons.stock_account.models.constants import COST_METHOD_SELECTION


class StockQuant(models.Model):
    _inherit = "stock.quant"

    value = fields.Monetary(
        "Value", compute="_compute_value", groups="stock.group_stock_manager"
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        groups="stock.group_stock_manager",
    )
    accounting_date = fields.Date(
        "Accounting Date",
        help="Date at which the accounting entries will be created"
        " in case of automated inventory valuation."
        " If empty, the inventory date will be used.",
    )
    cost_method = fields.Selection(
        string="Cost Method",
        selection=COST_METHOD_SELECTION,
        compute="_compute_cost_method",
    )

    @api.depends_context("company")
    @api.depends("product_categ_id.property_cost_method")
    def _compute_cost_method(self):
        for quant in self:
            quant.cost_method = (
                quant.product_categ_id.with_company(
                    quant.company_id
                ).property_cost_method
                or (quant.company_id or self.env.company).cost_method
            )

    @api.model
    def _should_exclude_for_valuation(self):
        """
        Determines if a quant should be excluded from valuation based on its ownership.
        :return: True if the quant should be excluded from valuation, False otherwise.
        """
        self.ensure_one()
        return self.owner_id and self.owner_id != self.company_id.partner_id

    @api.depends("company_id", "location_id", "owner_id", "product_id", "quantity")
    def _compute_value(self):
        self.fetch(
            [
                "company_id",
                "location_id",
                "owner_id",
                "product_id",
                "quantity",
                "lot_id",
            ]
        )
        self.value = 0
        valued_quants = self.filtered(
            lambda quant: (
                quant.location_id
                and quant.product_id
                and quant.location_id._should_be_valued()
                and not quant._should_exclude_for_valuation()
                and not quant.product_id.uom_id.is_zero(quant.quantity)
            )
        )
        # A quant is worth its share of the value its product (or lot) holds in its
        # company, so resolve that share once per (company, product, lot) rather than
        # once per quant -- and resolve a whole company at a time, because
        # `_with_valuation_context()` runs a location search that depends only on the
        # company, and `total_value` values every product of its prefetch set in one
        # pass.
        totals_by_key = {}
        for company, company_quants in valued_quants.grouped("company_id").items():
            # A lot-valuated product can still hold a quant with no lot (the guard on
            # enabling the flag only covers the stock present at the time), and that
            # quant is valued against the product, exactly as below.
            lot_quants = company_quants.filtered(
                lambda quant: quant.product_id.lot_valuated and quant.lot_id
            )
            for lot in lot_quants.lot_id.with_company(company):
                totals_by_key[company, lot.product_id.id, lot.id] = (
                    lot.product_qty,
                    lot.total_value,
                )

            products = (company_quants - lot_quants).product_id.with_company(company)
            # Ask for THIS company's value, not `total_value`: that field
            # deliberately sums every company in `env.companies` (and converts into
            # `env.company`'s currency), so dividing it by one company's quantity
            # gave every company's quant the whole group's value -- two companies
            # holding 100 and 500 both reported 600, and the list view's total
            # showed 1200.
            scoped = products._scoped_for_company(company)
            qty_by_product_id = {
                product.id: product.qty_available for product in scoped
            }
            value_by_product_id = scoped._run_valuation_batches()[1]
            for product in products:
                totals_by_key[company, product.id, False] = (
                    qty_by_product_id[product.id],
                    value_by_product_id.get(product.id, 0),
                )

        for quant in valued_quants:
            lot = quant.lot_id if quant.product_id.lot_valuated else False
            quantity, value = totals_by_key[
                quant.company_id, quant.product_id.id, lot.id if lot else False
            ]
            if quant.product_id.uom_id.is_zero(quantity):
                continue
            quant.value = quant.quantity * value / quantity

    def _read_group_select(self, aggregate_spec, query):
        # flag value as aggregatable, and manually sum the values from the
        # records in the group
        if aggregate_spec in ("value:sum", "value:sum_currency"):
            return super()._read_group_select("id:recordset", query)
        return super()._read_group_select(aggregate_spec, query)

    def _read_group_postprocess_aggregate(self, aggregate_spec, raw_values):
        if aggregate_spec in ("value:sum", "value:sum_currency"):
            column = super()._read_group_postprocess_aggregate(
                "id:recordset", raw_values
            )
            return (sum(records.mapped("value")) for records in column)
        return super()._read_group_postprocess_aggregate(aggregate_spec, raw_values)

    def _apply_inventory(self, date=None):
        for accounting_date, inventory_ids in groupby(
            self, key=lambda q: q.accounting_date
        ):
            inventories = self.env["stock.quant"].concat(*inventory_ids)
            if accounting_date:
                super(
                    StockQuant,
                    inventories.with_context(force_period_date=accounting_date),
                )._apply_inventory(date)
                inventories.accounting_date = False
            else:
                super(StockQuant, inventories)._apply_inventory(date)

    def _get_inventory_move_values(
        self,
        qty,
        location_id,
        location_dest_id,
        package_id=False,
        package_dest_id=False,
    ):
        res_move = super()._get_inventory_move_values(
            qty, location_id, location_dest_id, package_id, package_dest_id
        )
        if not self.env.context.get("inventory_name"):
            force_period_date = self.env.context.get("force_period_date", False)
            if force_period_date:
                if self.product_uom_id.is_zero(qty):
                    name = _("Product Quantity Confirmed")
                else:
                    name = _("Product Quantity Updated")
                if self.env.uid and self.env.uid != SUPERUSER_ID:
                    name += f" ({self.env.user.display_name})"
                res_move["inventory_name"] = name + _(
                    " [Accounted on %s]", force_period_date
                )
        return res_move

    @api.model
    def _get_inventory_fields_countable(self):
        """Let an inventory-mode `create` carry the accounting date.

        Renamed with the base method: the old `_get_inventory_fields_write` name
        promised a write allowlist that `write()` never consulted, so this override
        only ever affected creation -- which is what it is for. `accounting_date` was
        never blocked on write either way; that path gates on a deny-list.
        """
        return super()._get_inventory_fields_countable() + ["accounting_date"]
