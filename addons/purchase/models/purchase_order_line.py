from collections import defaultdict
from datetime import UTC, datetime, time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, SQL, get_lang
from odoo.tools.translate import _


class PurchaseOrderLine(models.Model):
    _name = "purchase.order.line"
    _inherit = [
        "mixin.order.line.fields",
        "mixin.order.line.amount",
        "mixin.order.line.invoice",
        "mixin.analytic",
    ]
    _description = "Purchase Order Line"
    _check_company_auto = True
    _order = "order_id, sequence, id"
    _rec_names_search = ["name", "order_id.name"]

    def _get_order_type(self):
        return "purchase"

    def _get_merge_date_field(self):
        return "date_commitment"


    order_id = fields.Many2one(comodel_name="purchase.order")
    partner_id = fields.Many2one(string="Vendor")
    user_id = fields.Many2one(string="Buyer")

    is_expense = fields.Boolean(
        help="Is true if the sales order line comes from an expense or a vendor bills",
    )

    parent_id = fields.Many2one(comodel_name="purchase.order.line")

    purchase_line_warn_msg = fields.Text(
        compute="_compute_purchase_line_warn_msg",
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Product attribute values that do not create variants",
        ondelete="restrict",
    )
    tax_ids = fields.Many2many(
        compute="_compute_tax_ids",
        store=True,
        precompute=True,
        readonly=False,
        domain="[('type_tax_use', '=', 'purchase')]",
    )
    selected_seller_id = fields.Many2one(
        comodel_name="product.supplierinfo",
        compute="_compute_selected_seller_id",
        store=True,
        precompute=True,
        help="The vendor pricelist entry that applies to this line based on "
        "partner, product, quantity, UoM, and date.",
    )
    price_unit_auto = fields.Float(
        help="Price from vendor/product. Compared with price_unit to detect manual overrides. "
        "When price_unit != price_unit_auto, the price is considered manually set.",
    )
    price_unit_product_uom = fields.Float(
        string="Unit Price Product UoM",
        min_display_digits="Product Price",
        compute="_compute_price_unit_product_uom",
        help="The Price of one unit of the product's Unit of Measure",
    )
    discount = fields.Float(
        aggregator="avg",
    )
    date_commitment = fields.Datetime(
        string="Expected Arrival",
        compute="_compute_date_commitment",
        store=True,
        precompute=True,
        readonly=False,
        index=True,
        help="Delivery date expected from vendor. This date respectively defaults to vendor pricelist lead time then today's date.",
    )
    date_is_manual = fields.Boolean(
        string="Date Manually Set",
        default=False,
        help="If checked, the expected arrival date was manually set and won't be "
        "automatically updated when the seller or order date changes.",
    )
    qty_transferred_method = fields.Selection(
        string="Received Qty Method",
        help="According to product configuration, the received quantity can be automatically computed by mechanism:\n"
        "  - Manual: the quantity is set manually on the line\n"
        "  - Stock Moves: the quantity comes from confirmed pickings\n",
    )
    qty_transferred = fields.Float(string="Received Qty")
    qty_transferred_at_date = fields.Float(string="Received")

    invoice_line_ids = fields.Many2many(
        relation="account_move_line_purchase_order_line_rel",
        column1="order_line_id",
        column2="move_line_id",
    )
    qty_invoiced_at_date = fields.Float(string="Billed")


    def _get_display_type_nullify_vals(self):
        return {**super()._get_display_type_nullify_vals(), "date_commitment": False}

    def _get_count_id(self, query):
        return SQL("order_id")

    def _get_fields_tracked_qty(self):
        return [*super()._get_fields_tracked_qty(), "qty_transferred"]

    def _collect_qty_changes(self, vals, tracked_fields):
        if self.env.context.get("accrual_entry_date"):
            tracked_fields = [f for f in tracked_fields if f != "qty_transferred"]
        return super()._collect_qty_changes(vals, tracked_fields)

    def _post_quantity_changes(self, field_name, changes):
        changes_by_order = defaultdict(list)
        for change in changes:
            changes_by_order[change["line"].order_id].append(change)
        for order, order_changes in changes_by_order.items():
            self._post_batched_quantity_changes(order, order_changes, field_name)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        lines_to_block = self._check_line_unlink()
        if lines_to_block:
            state_description = dict(
                self._fields["state"]._description_selection(self.env),
            )
            state_label = state_description[lines_to_block[0].state]
            raise UserError(
                _(
                    "Cannot delete a purchase order line which is in state '%s'.\n"
                    "Once a purchase order is confirmed, you can't remove lines that have been "
                    "invoiced or received (we need to track if something gets invoiced or received).\n"
                    "Set the quantity to 0 instead.",
                    state_label,
                ),
            )


    @api.depends("product_id.purchase_line_warn_msg")
    def _compute_purchase_line_warn_msg(self):
        self._compute_line_warn_msg("purchase_line_warn_msg")

    def _get_warning_group(self):
        return "purchase.group_warning_purchase"

    def _get_product_warn_field(self):
        return "purchase_line_warn_msg"

    @api.depends(
        "product_id",
        "product_id.uom_id",
        "product_id.uom_ids",
        "product_id.seller_ids",
        "product_id.seller_ids.product_uom_id",
    )
    def _compute_allowed_uom_ids(self):
        return super()._compute_allowed_uom_ids()

    def _get_extra_allowed_uoms(self):
        return self.product_id.seller_ids.filtered(
            lambda s: s.product_id.id in {False, self.product_id.id},
        ).product_uom_id

    @api.depends("company_id", "fiscal_position_id", "product_id")
    def _compute_tax_ids(self):
        return super()._compute_tax_ids()

    @api.depends("partner_id", "product_id")
    def _compute_product_uom_id(self):
        return super()._compute_product_uom_id()

    def _get_default_product_uom(self):
        seller_uom = False
        sellers = self._get_sellers_for_partner()
        if sellers and sellers[0].product_uom_id:
            seller_uom = sellers[0].product_uom_id
        return seller_uom or self.product_id.uom_id

    @api.depends(
        "partner_id", "date_order", "product_id", "product_id.seller_ids.min_qty"
    )
    def _compute_product_qty(self):
        return super()._compute_product_qty()

    def _product_qty_reset_triggered(self):
        return bool(
            (self._origin.product_id and self._origin.product_id != self.product_id)
            or (self._origin.partner_id and self._origin.partner_id != self.partner_id)
        )

    def _get_default_product_qty(self):
        date = fields.Date.context_today(self, timestamp=self.date_order)
        sellers = self._get_sellers_for_partner(date=date)
        sellers = sellers.filtered(
            lambda s: not s.product_id or s.product_id == self.product_id
        ).sorted(key=lambda r: r.min_qty)
        if sellers:
            return sellers[0].min_qty or 1.0
        return 1.0

    @api.depends(
        "partner_id",
        "date_order",
        "product_id",
        "product_id.seller_ids",
        "product_id.seller_ids.partner_id",
        "product_id.seller_ids.company_id",
        "product_id.seller_ids.min_qty",
        "product_id.seller_ids.date_start",
        "product_id.seller_ids.date_end",
        "product_id.seller_ids.product_uom_id",
        "product_uom_id",
        "product_qty",
        "company_id",
    )
    def _compute_selected_seller_id(self):
        non_accountable = self.filtered(lambda l: l.display_type or not l.product_id)
        non_accountable.selected_seller_id = False

        accountable_lines = self - non_accountable
        if not accountable_lines:
            return

        seller_cache = {}

        for line in accountable_lines:
            qty = abs(line.product_qty) or 1.0

            cache_key = (
                line.product_id.id,
                line.partner_id.id,
                line.order_id.id,
                line.product_uom_id.id,
                qty,
            )

            if cache_key not in seller_cache:
                params = line._get_select_sellers_params()
                seller = line.product_id.with_company(line.company_id)._select_seller(
                    partner_id=line.partner_id,
                    quantity=qty,
                    date=fields.Date.context_today(
                        line, timestamp=line.order_id.date_order
                    ),
                    uom_id=line.product_uom_id,
                    params=params,
                )
                seller_cache[cache_key] = seller or False

            line.selected_seller_id = seller_cache[cache_key]

    @api.depends("partner_id", "product_id", "selected_seller_id")
    def _compute_name(self):
        for line in self:
            if not line.product_id:
                continue
            line._set_product_description()

    def _get_line_description_lang(self):
        return self.partner_id.lang

    @api.depends(
        "selected_seller_id",
        "selected_seller_id.price",
        "selected_seller_id.discount",
        "selected_seller_id.currency_id",
        "selected_seller_id.product_uom_id",
        "product_id.standard_price",
        "product_id.supplier_taxes_id",
        "product_id.cost_currency_id",
        "product_uom_id",
        "company_id",
        "currency_id",
        "date_order",
        "tax_ids",
    )
    def _compute_price_and_discount(self):
        return super()._compute_price_and_discount()

    def _get_auto_price_and_discount(self):
        if self.selected_seller_id:
            return (
                self._get_price_from_seller(),
                self.selected_seller_id.discount or 0.0,
            )
        return self._get_price_from_product_cost(), 0.0

    @api.depends("date_order", "selected_seller_id", "selected_seller_id.delay")
    def _compute_date_commitment(self):
        accountable_lines = self.filtered(lambda l: not l.display_type and l.product_id)
        if not accountable_lines:
            return

        for line in accountable_lines:
            new_date = line._get_date_commitment(line.selected_seller_id)

            if not line.date_commitment:
                line.date_commitment = new_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                continue

            if line.date_commitment.date() == new_date.date():
                continue

            if line._origin.product_id and line._origin.product_id != line.product_id:
                line.date_commitment = new_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                line.date_is_manual = False
                continue

            if line.date_is_manual:
                continue

            if not line._origin.date_is_manual:
                valid_dates = line._get_seller_valid_dates()
                if line.date_commitment.date() in valid_dates:
                    line.date_commitment = new_date.strftime(
                        DEFAULT_SERVER_DATETIME_FORMAT
                    )

    @api.depends("product_id.uom_id", "product_uom_id", "price_unit")
    def _compute_price_unit_product_uom(self):
        for line in self:
            line.price_unit_product_uom = (
                not line.display_type
                and not line.is_downpayment
                and line.product_uom_id._compute_price(
                    line.price_unit,
                    line.product_id.uom_id,
                )
            )

    @api.depends("product_qty", "price_unit", "discount", "tax_ids")
    def _compute_amounts(self):
        AccountTax = self.env["account.tax"]
        for line in self:
            if line.display_type:
                line.price_subtotal = False
                line.price_total = False
                line.price_tax = False
                continue
            company = line.company_id or self.env.company
            base_line = line._prepare_base_line_for_taxes_computation()
            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)
            line.price_subtotal = base_line["tax_details"]["total_excluded_currency"]
            line.price_total = base_line["tax_details"]["total_included_currency"]
            line.price_tax = line.price_total - line.price_subtotal

    @api.depends(
        "state",
        "product_id.bill_policy",
        "product_qty",
        "price_unit_discounted_taxexc",
        "tax_ids",
        "price_total",
        "qty_transferred",
        "invoice_line_ids",
        "invoice_line_ids.parent_state",
        "invoice_line_ids.quantity",
        "invoice_line_ids.discount",
        "invoice_line_ids.price_subtotal",
        "invoice_line_ids.price_total",
    )
    def _compute_invoice_amounts(self):
        for line in self:
            line._compute_invoice_amounts_single()

    def _compute_invoice_amounts_single(self):
        if self.display_type:
            self._reset_invoice_amounts()
            return

        invoice_lines = self._get_posted_invoice_lines()
        invoiced = self._sum_invoiced_amounts(invoice_lines)

        self.qty_invoiced = invoiced["qty"]
        self.amount_taxexc_invoiced = invoiced["amount_taxexc"]
        self.amount_taxinc_invoiced = invoiced["amount_taxinc"]

        if self.state in ("draft", "cancel"):
            self._reset_to_invoice_amounts()
            return

        self._compute_to_invoice_amounts(invoice_lines, invoiced)

    def _compute_to_invoice_amounts(self, invoice_lines, invoiced):
        qty_to_consider = self._get_qty_to_consider_for_billing()
        price_subtotal = self._get_billable_subtotal(qty_to_consider)

        if self._has_discount_differences(invoice_lines):
            amount_invoiced = self._sum_invoiced_with_discount_adjustment(invoice_lines)
            self.amount_taxexc_to_invoice = max(price_subtotal - amount_invoiced, 0.0)
        else:
            self.amount_taxexc_to_invoice = max(
                price_subtotal - invoiced["amount_taxexc"],
                0.0,
            )

        unit_price_total = (
            self.price_total / self.product_qty if self.product_qty else 0.0
        )
        self.amount_taxinc_to_invoice = unit_price_total * (
            qty_to_consider - invoiced["qty"]
        )
        self.qty_to_invoice = qty_to_consider - invoiced["qty"]

    @api.depends(
        "qty_to_invoice",
        "qty_invoiced",
        "product_qty",
        "qty_transferred",
        "product_id.bill_policy",
        "amount_taxexc_to_invoice",
    )
    def _compute_invoice_state(self):
        return super()._compute_invoice_state()


    @api.onchange("date_commitment")
    def _onchange_date_commitment(self):
        if (
            self._origin.date_commitment
            and self.date_commitment != self._origin.date_commitment
        ):
            self.date_is_manual = True


    def _convert_to_middle_of_day(self, date):
        return (
            datetime.combine(date, time(12))
            .replace(tzinfo=self.order_id.get_timezone())
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def _get_billable_subtotal(self, qty):
        subtotal = self.price_unit_discounted_taxexc * qty

        if self.tax_ids.filtered(lambda t: t.price_include):
            subtotal = self.tax_ids.compute_all(
                self.price_unit_discounted_taxexc,
                currency=self.currency_id,
                quantity=qty,
                product=self.product_id,
                partner=self.order_id.partner_id,
            )["total_excluded"]

        return subtotal

    @api.model
    def _get_date_commitment(self, seller, po=False):
        date_order = po.date_order if po else self.order_id.date_order
        if date_order:
            return date_order + relativedelta(days=seller.delay if seller else 0)
        else:
            return datetime.today() + relativedelta(days=seller.delay if seller else 0)

    def _get_line_description(self, product_lang):
        self.ensure_one()
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase
        no_variant_attribute_values = self.with_context(
            product_lang.env.context,
        ).product_no_variant_attribute_value_ids
        for no_variant_attribute_value in no_variant_attribute_values:
            name += (
                "\n"
                + no_variant_attribute_value.attribute_id.name
                + ": "
                + no_variant_attribute_value.name
            )
        return name

    def _get_price_precision(self):
        self.ensure_one()
        return max(
            self.currency_id.decimal_places,
            self.env["decimal.precision"].get_precision("Product Price"),
        )

    def _get_catalog_single_line_data(self, **kwargs):
        catalog_info = self.order_id._get_product_price_and_data(self.product_id)
        catalog_info.update(
            quantity=self.product_qty,
            price=self._get_price_discounted(),
            readOnly=self.order_id._is_readonly(),
        )
        if self.product_id.uom_id != self.product_uom_id:
            catalog_info["uomDisplayName"] = self.product_uom_id.display_name
        return catalog_info

    def _get_catalog_multi_line_data(self, **kwargs):
        return self.order_id._get_product_price_and_data(self.product_id)

    def _get_price_from_seller(self):
        self.ensure_one()
        seller = self.selected_seller_id

        price_unit = self.env["account.tax"]._fix_tax_included_price_company(
            seller.price,
            self.product_id.supplier_taxes_id,
            self.tax_ids,
            self.company_id,
        )

        price_unit = seller.currency_id._convert(
            price_unit,
            self.currency_id,
            self.company_id,
            self.date_order or fields.Date.context_today(self),
            False,
        )

        return seller.product_uom_id._compute_price_estimate(
            price_unit, self.product_uom_id
        )

    def _get_price_from_product_cost(self):
        self.ensure_one()

        po_line_uom = self.product_uom_id or self.product_id.uom_id

        price_unit = self.env["account.tax"]._fix_tax_included_price_company(
            self.product_id.uom_id._compute_price_estimate(
                self.product_id.standard_price,
                po_line_uom,
            ),
            self.product_id.supplier_taxes_id,
            self.tax_ids,
            self.company_id,
        )

        return self.product_id.cost_currency_id._convert(
            price_unit,
            self.currency_id,
            self.company_id,
            self.date_order or fields.Date.context_today(self),
            False,
        )

    def _get_qty_to_consider_for_billing(self):
        if self.product_id.bill_policy == "transferred":
            return self.qty_transferred
        return self.product_qty

    def _get_select_sellers_params(self):
        self.ensure_one()
        return {
            "order_id": self.order_id,
            "force_uom": True,
        }

    def _get_sellers_for_partner(self, date=None):
        self.ensure_one()
        if not self.product_id or not self.partner_id:
            return self.env["product.supplierinfo"]

        sellers = self.product_id.seller_ids

        partner = self.partner_id
        parent = self.partner_id.parent_id
        sellers = sellers.filtered(lambda s: s.partner_id in (partner, parent))

        if date:
            sellers = sellers.filtered(
                lambda s: (
                    (not s.date_start or s.date_start <= date)
                    and (not s.date_end or s.date_end >= date)
                )
            )

        return sellers

    def _get_seller_valid_dates(self):
        self.ensure_one()
        valid_dates = set()

        for seller in self.product_id.seller_ids:
            seller_date = self._get_date_commitment(seller)
            valid_dates.add(seller_date.date())

        no_seller_date = self._get_date_commitment(False)
        valid_dates.add(no_seller_date.date())

        return valid_dates

    def _get_invoice_line_link_field(self):
        return "purchase_line_ids"

    def _invoiced_on_transferred(self):
        return self.product_id.bill_policy == "transferred"

    def _prepare_aml_vals(self, **optional_values):
        self.ensure_one()
        move = optional_values.pop("move", None)
        res = super()._prepare_aml_vals(**optional_values)
        aml_currency = (move and move.currency_id) or self.currency_id
        date = (move and move.date) or fields.Date.today()
        res["quantity"] = (
            -self.qty_to_invoice
            if move and move.move_type == "in_refund"
            else self.qty_to_invoice
        )
        res["price_unit"] = self.currency_id._convert(
            self.price_unit,
            aml_currency,
            self.company_id,
            date,
            round=False,
        )
        return res

    def _post_batched_quantity_changes(self, order, changes, change_type):
        if not changes:
            return

        if len(changes) == 1:
            change = changes[0]
            if change_type == "product_qty":
                order.message_post_with_source(
                    "purchase.track_po_line_template",
                    render_values={
                        "line": change["line"],
                        "product_qty": change["new_qty"],
                    },
                    subtype_xmlid="mail.mt_note",
                )
            elif change_type == "qty_transferred":
                order.message_post_with_source(
                    "purchase.track_po_line_qty_transferred_template",
                    render_values={
                        "line": change["line"],
                        "qty_transferred": change["new_qty"],
                    },
                    subtype_xmlid="mail.mt_note",
                )
        else:
            order.message_post_with_source(
                "purchase.track_po_qty_update_template",
                render_values={
                    "changes": changes,
                    "change_type": change_type,
                    "count": len(changes),
                },
                subtype_xmlid="mail.mt_note",
            )

    @api.model
    def _prepare_purchase_order_line(
        self,
        product_id,
        product_qty,
        product_uom_id,
        company_id,
        partner_id,
        po,
    ):
        values = self.env.context.get("procurement_values", {})
        uom_po_qty = product_uom_id._compute_quantity(
            product_qty,
            product_id.uom_id,
            rounding_method="HALF-UP",
        )
        today = fields.Date.context_today(self)
        seller = product_id.with_company(company_id)._select_seller(
            partner_id=partner_id,
            quantity=product_qty if values.get("force_uom") else uom_po_qty,
            date=max(fields.Date.context_today(self, timestamp=po.date_order), today),
            uom_id=product_uom_id if values.get("force_uom") else product_id.uom_id,
            params={"force_uom": values.get("force_uom")},
        )
        if (
            seller
            and (seller.product_uom_id or seller.product_tmpl_id.uom_id)
            != product_uom_id
        ):
            uom_po_qty = product_id.uom_id._compute_quantity(
                uom_po_qty,
                seller.product_uom_id,
                rounding_method="HALF-UP",
            )

        tax_domain = self.env["account.tax"]._check_company_domain(company_id)
        product_taxes = product_id.supplier_taxes_id.filtered_domain(tax_domain)
        taxes = po.fiscal_position_id.map_tax(product_taxes)

        if seller:
            price_unit = (
                seller.product_uom_id._compute_price_estimate(
                    seller.price, product_uom_id
                )
                if product_uom_id
                else seller.price
            )
            price_unit = self.env["account.tax"]._fix_tax_included_price_company(
                price_unit,
                product_taxes,
                taxes,
                company_id,
            )
        else:
            price_unit = 0
        if (
            price_unit
            and seller
            and po.currency_id
            and seller.currency_id != po.currency_id
        ):
            price_unit = seller.currency_id._convert(
                price_unit,
                po.currency_id,
                po.company_id,
                po.date_order or fields.Date.today(),
            )

        product_lang = product_id.with_prefetch().with_context(
            lang=partner_id.lang,
            partner_id=partner_id.id,
        )
        name = product_lang.with_context(seller_id=seller.id).display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase

        date_commitment = self.order_id.date_commitment or self._get_date_commitment(
            seller,
            po=po,
        )
        discount = seller.discount or 0.0

        return {
            "name": name,
            "product_qty": product_qty if product_uom_id else uom_po_qty,
            "product_id": product_id.id,
            "product_uom_id": product_uom_id.id or seller.product_uom_id.id,
            "price_unit": price_unit,
            "date_commitment": date_commitment,
            "tax_ids": [Command.set(taxes.ids)],
            "order_id": po.id,
            "discount": discount,
        }

    def _reset_invoice_amounts(self):
        self.qty_invoiced = False
        self.qty_to_invoice = False
        self.amount_taxexc_invoiced = False
        self.amount_taxexc_to_invoice = False
        self.amount_taxinc_invoiced = False
        self.amount_taxinc_to_invoice = False

    def _reset_to_invoice_amounts(self):
        self.amount_taxexc_to_invoice = 0.0
        self.amount_taxinc_to_invoice = 0.0
        self.qty_to_invoice = 0.0

    def _set_product_description(self):
        self.ensure_one()

        lang = get_lang(self.env, self.partner_id.lang).code

        seller_id = self.selected_seller_id.id if self.selected_seller_id else None
        product_ctx = {"seller_id": seller_id, "lang": lang}
        new_default = self._get_line_description(
            self.product_id.with_context(product_ctx),
        )

        if not self.name:
            self.name = new_default
            return

        if self.name == new_default:
            return

        if self._origin.product_id and self._origin.product_id != self.product_id:
            self.name = new_default
            return

        for seller in self.product_id.seller_ids:
            seller_ctx = {"seller_id": seller.id, "lang": lang}
            seller_default = self._get_line_description(
                self.product_id.with_context(seller_ctx),
            )
            if self.name == seller_default:
                self.name = new_default
                return

        no_seller_ctx = {"seller_id": None, "lang": lang}
        generic_default = self._get_line_description(
            self.product_id.with_context(no_seller_ctx),
        )
        if self.name == generic_default:
            self.name = new_default
            return

        for seller in self.product_id.seller_ids:
            seller_display_name = self.product_id.with_context(
                {"seller_id": seller.id, "lang": lang},
            ).display_name
            if self.name.startswith(seller_display_name):
                if not self.selected_seller_id:
                    self.name = (
                        self.product_id.with_context(
                            {"seller_id": None, "lang": lang},
                        ).display_name
                        + self.name[len(seller_display_name) :]
                    )
                elif seller.id != self.selected_seller_id.id:
                    self.name = (
                        self.product_id.with_context(
                            {"seller_id": self.selected_seller_id.id, "lang": lang},
                        ).display_name
                        + self.name[len(seller_display_name) :]
                    )
                return


    def _sum_invoiced_amounts(self, invoice_lines):
        qty = 0.0
        amount_taxexc = 0.0
        amount_taxinc = 0.0

        for inv_line in invoice_lines:
            sign = inv_line.move_id.direction_sign
            date = inv_line.invoice_date or fields.Date.today()

            qty += sign * inv_line.product_uom_id._compute_quantity_reconcile(
                inv_line.quantity,
                self.product_uom_id,
            )
            amount_taxexc += sign * inv_line.currency_id._convert(
                inv_line.price_subtotal,
                self.currency_id,
                self.company_id,
                date,
            )
            amount_taxinc += sign * inv_line.currency_id._convert(
                inv_line.price_total,
                self.currency_id,
                self.company_id,
                date,
            )

        return {
            "qty": qty,
            "amount_taxexc": amount_taxexc,
            "amount_taxinc": amount_taxinc,
        }

    def _sum_invoiced_with_discount_adjustment(self, invoice_lines):
        total = 0.0

        for inv_line in invoice_lines:
            converted_price = inv_line.currency_id._convert(
                inv_line.price_unit,
                self.currency_id,
                self.company_id,
                inv_line.date or fields.Date.today(),
                round=False,
            )
            line_amount = converted_price * inv_line.quantity

            if inv_line.tax_ids.filtered(lambda t: t.price_include):
                line_amount = inv_line.tax_ids.compute_all(line_amount)[
                    "total_excluded"
                ]

            total += line_amount

        return total

    def _update_date_commitment(self, updated_date):
        self.date_commitment = updated_date


    def _has_discount_differences(self, invoice_lines):
        return any(inv_line.discount != self.discount for inv_line in invoice_lines)

    def _price_update_blocked(self):
        if self.invoice_line_ids:
            return True
        if self.state == "done" and self._origin.id:
            original_currency = self._origin.currency_id
            if original_currency and original_currency != self.currency_id:
                return True
        return super()._price_update_blocked()

    def _check_write_guards(self, write_vals):
        for method_name in self._get_check_write_guards():
            if hasattr(self, method_name):
                getattr(self, method_name)(write_vals)
