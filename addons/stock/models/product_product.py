import logging
from ast import literal_eval
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time
from typing import NamedTuple

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.libs.barcode import check_barcode_encoding
from odoo.libs.numbers import float_compare
from odoo.tools import SQL, Query
from odoo.tools.mail import html2plaintext, is_html_empty

from odoo.addons.stock.const import PY_OPERATORS, QUANTITY_FIELDS

_logger = logging.getLogger(__name__)


class QuantityScope(NamedTuple):
    """What one quantity computation reads, before anything is read."""

    quant: Domain
    expired_quant: Domain | None
    move_in_todo: Domain
    move_out_todo: Domain
    move_in_done: Domain
    move_out_done: Domain
    dates_in_the_past: bool


class QuantityReads(NamedTuple):
    """The raw grouped sums behind the quantity fields, keyed by product id."""

    quants: dict
    expired_unreserved: dict
    moves_in: dict
    moves_out: dict
    moves_in_past: dict
    moves_out_past: dict


class ProductProduct(models.Model):
    _inherit = "product.product"

    stock_quant_ids = fields.One2many(
        comodel_name="stock.quant",
        inverse_name="product_id",
    )
    stock_move_ids = fields.One2many(
        comodel_name="stock.move",
        inverse_name="product_id",
    )
    qty_available = fields.Float(
        string="Quantity On Hand",
        digits="Product Unit",
        compute="_compute_quantities",
        compute_sudo=False,
        inverse="_inverse_qty_available",
        search="_search_qty_available",
        help="Current quantity of products.\n"
        "In a context with a single Stock Location, this includes "
        "goods stored at this Location, or any of its children.\n"
        "In a context with a single Warehouse, this includes "
        "goods stored in the Stock Location of this Warehouse, or any "
        "of its children.\n"
        "Otherwise, this includes goods stored in any Stock Location "
        "with 'internal' type.",
    )
    qty_available_virtual = fields.Float(
        string="Forecasted Quantity",
        digits="Product Unit",
        compute="_compute_quantities",
        compute_sudo=False,
        search="_search_virtual_available",
        help="Forecast quantity (computed as Quantity On Hand "
        "- Outgoing + Incoming)\n"
        "In a context with a single Stock Location, this includes "
        "goods stored in this location, or any of its children.\n"
        "In a context with a single Warehouse, this includes "
        "goods stored in the Stock Location of this Warehouse, or any "
        "of its children.\n"
        "Otherwise, this includes goods stored in any Stock Location "
        "with 'internal' type.",
    )
    qty_free = fields.Float(
        string="Free To Use Quantity",
        digits="Product Unit",
        compute="_compute_quantities",
        compute_sudo=False,
        search="_search_free_qty",
        help="Available quantity (computed as Quantity On Hand "
        "- reserved quantity)\n"
        "In a context with a single Stock Location, this includes "
        "goods stored in this location, or any of its children.\n"
        "In a context with a single Warehouse, this includes "
        "goods stored in the Stock Location of this Warehouse, or any "
        "of its children.\n"
        "Otherwise, this includes goods stored in any Stock Location "
        "with 'internal' type.",
    )
    qty_incoming = fields.Float(
        string="Incoming",
        digits="Product Unit",
        compute="_compute_quantities",
        compute_sudo=False,
        search="_search_incoming_qty",
        help="Quantity of planned incoming products.\n"
        "In a context with a single Stock Location, this includes "
        "goods arriving to this Location, or any of its children.\n"
        "In a context with a single Warehouse, this includes "
        "goods arriving to the Stock Location of this Warehouse, or "
        "any of its children.\n"
        "Otherwise, this includes goods arriving to any Stock "
        "Location with 'internal' type.",
    )
    qty_outgoing = fields.Float(
        string="Outgoing",
        digits="Product Unit",
        compute="_compute_quantities",
        compute_sudo=False,
        search="_search_outgoing_qty",
        help="Quantity of planned outgoing products.\n"
        "In a context with a single Stock Location, this includes "
        "goods leaving this Location, or any of its children.\n"
        "In a context with a single Warehouse, this includes "
        "goods leaving the Stock Location of this Warehouse, or "
        "any of its children.\n"
        "Otherwise, this includes goods leaving any Stock "
        "Location with 'internal' type.",
    )

    orderpoint_ids = fields.One2many(
        comodel_name="stock.warehouse.orderpoint",
        inverse_name="product_id",
        string="Minimum Stock Rules",
    )
    count_moves_in = fields.Integer(
        compute="_compute_count_moves",
        compute_sudo=False,
        help="Number of incoming stock moves in the past 12 months",
    )
    count_moves_out = fields.Integer(
        compute="_compute_count_moves",
        compute_sudo=False,
        help="Number of outgoing stock moves in the past 12 months",
    )
    count_reordering_rules = fields.Integer(
        string="Reordering Rules",
        compute="_compute_count_reordering_rules",
        compute_sudo=False,
    )
    reordering_qty_min = fields.Float(
        compute="_compute_count_reordering_rules",
        compute_sudo=False,
    )
    reordering_qty_max = fields.Float(
        compute="_compute_count_reordering_rules",
        compute_sudo=False,
    )
    putaway_rule_ids = fields.One2many(
        comodel_name="stock.putaway.rule",
        inverse_name="product_id",
        string="Putaway Rules",
    )
    storage_category_capacity_ids = fields.One2many(
        comodel_name="stock.storage.category.capacity",
        inverse_name="product_id",
        string="Storage Category Capacity",
    )
    show_on_hand_qty_status_button = fields.Boolean(
        compute="_compute_show_qty_status_button",
    )
    show_forecasted_qty_status_button = fields.Boolean(
        compute="_compute_show_qty_status_button",
    )
    show_qty_update_button = fields.Boolean(
        compute="_compute_show_qty_update_button",
    )
    valid_ean = fields.Boolean(
        string="Barcode is valid EAN",
        compute="_compute_valid_ean",
    )
    lot_properties_definition = fields.PropertiesDefinition("Lot Properties")
    lot_ids = fields.One2many(
        comodel_name="stock.lot",
        inverse_name="product_id",
        string="Lot/Serial Numbers",
    )
    count_lot_ids = fields.Integer(
        compute="_compute_count_lot_ids",
        string="Lots Count",
    )

    def write(self, vals):
        if "active" in vals:
            self.filtered(lambda p: p.active != vals["active"]).with_context(
                active_test=False
            ).orderpoint_ids.write({"active": vals["active"]})
        return super().write(vals)

    @api.model
    def view_header_get(self, view_id, view_type):
        res = super().view_header_get(view_id, view_type)
        if (
            not res
            and self.env.context.get("active_id")
            and self.env.context.get("active_model") == "stock.location"
        ):
            return _(
                "Products: %(location)s",
                location=self.env["stock.location"]
                .browse(self.env.context["active_id"])
                .name,
            )
        return res

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        """Relabel the quantity fields to match the location the context scopes them to.

        The scope itself accepts an id, a name to match, or a list of either
        (`_get_domain_locations`), so the labels resolve the value the same way rather
        than only understanding a bare id -- a list or a name used to filter the numbers
        while leaving them labelled "Quantity On Hand".

        Only an unambiguous single location can name a column, so a scope resolving to
        several is left with the generic labels. A *bad* value is skipped rather than
        raised on, unlike the scope path: labels are cosmetic, and breaking view loading
        over a stray context key is worse than not relabelling.
        """
        res = super().fields_get(allfields, attributes)
        context_location = self.env.context.get("location") or self.env.context.get(
            "search_location",
        )
        if context_location:
            if not isinstance(context_location, list):
                context_location = [context_location]
            try:
                location_ids = self._resolve_context_record_ids(
                    "stock.location", context_location
                )
            except ValueError:
                location_ids = set()
            location = self.env["stock.location"].browse(
                next(iter(location_ids)) if len(location_ids) == 1 else ()
            )
            relabels = {
                "supplier": {
                    "qty_available_virtual": _("Future Receipts"),
                    "qty_available": _("Received Qty"),
                },
                "internal": {
                    "qty_available_virtual": _("Forecasted Quantity"),
                },
                "customer": {
                    "qty_available_virtual": _("Future Deliveries"),
                    "qty_available": _("Delivered Qty"),
                },
                "inventory": {
                    "qty_available_virtual": _("Future P&L"),
                    "qty_available": _("P&L Qty"),
                },
                "production": {
                    "qty_available_virtual": _("Future Productions"),
                    "qty_available": _("Produced Qty"),
                },
            }
            for field_name, label in relabels.get(location.usage, {}).items():
                if res.get(field_name):
                    res[field_name]["string"] = label
        return res

    @api.depends("lot_ids")
    def _compute_count_lot_ids(self):
        counts = dict(
            self.env["stock.lot"]._read_group(
                [("product_id", "in", self.ids)],
                ["product_id"],
                ["__count"],
            )
        )
        for product in self:
            product.count_lot_ids = counts.get(product._origin, 0)

    @api.depends(
        "stock_move_ids.move_line_ids.state",
        "stock_move_ids.move_line_ids.date",
    )
    def _compute_count_moves(self):
        """Count this product's done receipt/delivery lines over the last 12 months.

        The dependency names ``stock.move.line``, which is what the read-groups below
        actually read. Declaring ``stock_move_ids.state`` instead was right often enough
        to hide the gap -- validating a picking writes the move's state and does refresh
        the count -- but the value follows the *line's* state and date, and backdating a
        line of an already-done move left it stale.

        ``picking_code`` is deliberately absent: it is a non-stored related on the
        picking type, so it cannot carry a dependency, and a picking type's code does not
        change under a done move.
        """
        one_year_ago = fields.Datetime.now() - relativedelta(years=1)

        def _counts_by_product(picking_code):
            return dict(
                self.env["stock.move.line"]._read_group(
                    [
                        ("product_id", "in", self.ids),
                        ("state", "=", "done"),
                        ("picking_code", "=", picking_code),
                        ("date", ">=", one_year_ago),
                    ],
                    ["product_id"],
                    ["__count"],
                )
            )

        res_incoming = _counts_by_product("incoming")
        res_outgoing = _counts_by_product("outgoing")
        for product in self:
            product.count_moves_in = res_incoming.get(product._origin, 0)
            product.count_moves_out = res_outgoing.get(product._origin, 0)

    @api.depends("orderpoint_ids.product_min_qty", "orderpoint_ids.product_max_qty")
    def _compute_count_reordering_rules(self):
        read_group_res = self.env["stock.warehouse.orderpoint"]._read_group(
            [("product_id", "in", self.ids)],
            ["product_id"],
            ["__count", "product_min_qty:sum", "product_max_qty:sum"],
        )
        mapped_res = {product: aggregates for product, *aggregates in read_group_res}
        for product in self:
            count, product_min_qty_sum, product_max_qty_sum = mapped_res.get(
                product._origin, (0, 0, 0)
            )
            product.count_reordering_rules = count
            product.reordering_qty_min = product_min_qty_sum
            product.reordering_qty_max = product_max_qty_sum

    @api.depends(
        "product_tmpl_id.show_on_hand_qty_status_button",
        "product_tmpl_id.show_forecasted_qty_status_button",
    )
    def _compute_show_qty_status_button(self):
        for product in self:
            product.show_on_hand_qty_status_button = (
                product.product_tmpl_id.show_on_hand_qty_status_button
            )
            product.show_forecasted_qty_status_button = (
                product.product_tmpl_id.show_forecasted_qty_status_button
            )

    @api.depends("product_tmpl_id.tracking")
    def _compute_show_qty_update_button(self):
        for product in self:
            product.show_qty_update_button = (
                product.product_tmpl_id._should_open_product_quants()
            )

    @api.depends("barcode")
    def _compute_valid_ean(self):
        self.valid_ean = False
        for product in self:
            if product.barcode:
                product.valid_ean = check_barcode_encoding(
                    product.barcode.rjust(14, "0"), "gtin14"
                )

    @api.depends_context(
        "lot_id",
        "owner_id",
        "owners",
        "package_id",
        "from_date",
        "to_date",
        "location",
        "warehouse_id",
        "search_location",
        "search_warehouse",
        "allowed_company_ids",
        # Read further down the chain, and every one of them changes the answer:
        # `strict` and `skip_in_progress` in `_get_domain_locations_new`,
        # `with_expiration` and `fresh_qty_forecast` in `_expired_quant_domain`.
        # Left out of the cache key, one scope answered with the other's value --
        # whichever was computed first, in either direction. The template's roll-up
        # declares the same four: it reads these fields, so the key has to match or
        # the narrow read is served the wide answer one level down.
        "strict",
        "skip_in_progress",
        "with_expiration",
        "fresh_qty_forecast",
    )
    @api.depends(
        "stock_move_ids.product_qty", "stock_move_ids.state", "stock_move_ids.quantity"
    )
    def _compute_quantities(self):
        """Fill the five quantity fields for every product in ``self``.

        Services have no quantities and are left out of the computation, so they are
        zeroed directly; every other product is written once, from the values
        ``_prepare_quantities_vals`` returned.

        The whole set is rebound through ``skip_qty_available_update`` because
        ``qty_available`` is the one field with an inverse, which would otherwise post an
        inventory adjustment for a value this method just computed.

        ``type`` is read with prefetching off so that filtering services out does not
        drag every other field of the set along; the caller's own setting is then
        restored rather than hardcoded back on, since ``_search_product_quantity``
        deliberately turns it off.
        """
        prefetch_fields = self.env.context.get("prefetch_fields", True)
        guarded = self.with_context(skip_qty_available_update=True)
        products = (
            guarded.with_context(prefetch_fields=False)
            .filtered(lambda p: p.type != "service")
            .with_context(prefetch_fields=prefetch_fields)
        )
        for field_name in QUANTITY_FIELDS:
            (guarded - products)[field_name] = 0.0
        res = products._prepare_quantities_vals(
            self.env.context.get("lot_id"),
            self.env.context.get("owner_id"),
            self.env.context.get("package_id"),
            self.env.context.get("from_date"),
            self.env.context.get("to_date"),
        )
        for product in products:
            product.update(res[product.id])

    def _inverse_qty_available(self):
        """Apply a manual on-hand adjustment from the product form.

        Skipped when the write comes from ``_compute_quantities`` itself.

        The adjustment lands in each product's *own* company, not the active one:
        pairing a company-B product with company-A's stock location fails the
        multi-company check with a message that blames the warehouse setup. Products are
        therefore grouped by company and one warehouse resolved per group, which also
        avoids a search per product.

        ``_warehouse_redirect_warning`` raises a redirect to the warehouse
        configuration; it falls through only during module installation (registry not
        ready), where the adjustment is skipped rather than crashing on a False
        location.
        """
        if self.env.context.get("skip_qty_available_update", False):
            return
        self._apply_qty_available([product.qty_available for product in self])

    def _apply_qty_available(self, quantities):
        """Adjust on-hand quantities for the whole set in one inventory adjustment.

        Takes the quantities explicitly instead of reading ``qty_available`` back, so
        a caller that never wrote the field -- ``product.template.create`` -- reaches
        the same batched path rather than one adjustment per distinct value.

        When the context scopes quantities to a location or a warehouse, the adjustment
        lands *there*: `_compute_quantities` reads through that scope, so writing outside
        it made the field disagree with itself -- setting 9 under one warehouse put the
        stock in another and left the scoped value reading 0. See
        `_resolve_inventory_location`.
        """
        products_to_update = self.browse()
        quantities_to_apply = []
        for product, quantity in zip(self, quantities, strict=True):
            if product.type != "consu" or not product.is_storable:
                continue
            if (
                float_compare(
                    quantity,
                    0.0,
                    precision_rounding=product.uom_id.rounding,
                )
                < 0
            ):
                raise UserError(
                    _(
                        "The quantity on hand of %(product)s cannot be set to a negative value.",
                        product=product.display_name,
                    ),
                )
            products_to_update += product
            quantities_to_apply.append(quantity)
        if not products_to_update:
            return
        # Resolved only once there is something to adjust, so a set of services under an
        # ambiguous scope stays the no-op it has always been rather than raising.
        scoped_location = self._resolve_inventory_location()
        quantity_by_product = dict(
            zip(products_to_update, quantities_to_apply, strict=True)
        )
        if scoped_location:
            vals_list = [
                {
                    "product_id": product.id,
                    "location_id": scoped_location.id,
                    "inventory_quantity": quantity_by_product[product],
                }
                for product in products_to_update
            ]
        else:
            products_by_company = defaultdict(self.browse)
            for product in products_to_update:
                products_by_company[product.company_id or self.env.company] += product
            warehouses = self.env["stock.warehouse"].search(
                [("company_id", "in", [company.id for company in products_by_company])],
            )
            warehouse_by_company = {}
            for warehouse in warehouses:
                warehouse_by_company.setdefault(warehouse.company_id, warehouse)

            vals_list = []
            for company, products in products_by_company.items():
                warehouse = warehouse_by_company.get(company)
                if not warehouse:
                    self.env["stock.warehouse"]._warehouse_redirect_warning()
                    return
                vals_list += [
                    {
                        "product_id": product.id,
                        "location_id": warehouse.lot_stock_id.id,
                        "inventory_quantity": quantity_by_product[product],
                    }
                    for product in products
                ]
        quants = (
            self.env["stock.quant"]
            .with_context(inventory_mode=True, from_inverse_qty=True)
            .create(vals_list)
        )
        quants._apply_inventory()

    def _resolve_inventory_location(self):
        """The single internal location an on-hand adjustment should target, or empty.

        Empty means "the context named no scope" -- the caller then falls back to one
        warehouse per product company, which is the only sensible answer when nothing
        says otherwise and the products may span companies.

        A scope naming several internal locations has **no** correct answer: the value
        being written is a total over all of them, and splitting it across them is a
        guess. That raises rather than silently picking one, which is what the previous
        behaviour amounted to. A warehouse scope is the exception -- it names one place
        by construction, its `lot_stock_id` -- so the common case still works.
        """
        location_ids = self._scope_location_ids()
        if location_ids is None:
            return self.env["stock.location"].browse()
        locations = self.env["stock.location"].browse(location_ids)
        warehouses = locations.warehouse_id
        if len(locations) == 1 and locations.usage == "internal":
            return locations
        # A warehouse scope resolves to that warehouse's view location, whose stock
        # location is the unambiguous target.
        if len(warehouses) == 1 and locations == warehouses.view_location_id:
            return warehouses.lot_stock_id
        raise UserError(
            _(
                "The quantity on hand cannot be set while the view is scoped to "
                "%(count)s locations (%(locations)s): the value is a total over all of "
                "them, and there is no way to tell how it should be split. Scope the "
                "view to a single location or warehouse, or use an inventory "
                "adjustment.",
                count=len(locations),
                locations=", ".join(locations.mapped("display_name")[:5]) or "none",
            ),
        )

    def _search_qty_available(self, operator, value):
        # The quant-only fast path answers only "on hand, now, whoever owns it". A date
        # window or an owner filter changes the answer, so those fall through to the full
        # pass -- but only when they carry a value. `to_date=False` is "no cutoff", which
        # is what the fast path already computes; testing key *presence* abandoned it for
        # a context that asked for nothing. `owners` stays a presence test: an empty list
        # is a real filter there, selecting the stock that has no owner.
        if not (
            self.env.context.get("from_date")
            or self.env.context.get("to_date")
            or "owners" in self.env.context
        ):
            op = PY_OPERATORS.get(operator)
            if op is not None and op(0.0, value):
                return self._search_product_quantity(operator, value, "qty_available")
            product_ids = self._search_qty_available_new(
                operator,
                value,
                self.env.context.get("lot_id"),
                self.env.context.get("owner_id"),
                self.env.context.get("package_id"),
            )
            if product_ids is not NotImplemented:
                return [("id", "in", product_ids)]
        return self._search_product_quantity(operator, value, "qty_available")

    def _search_virtual_available(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_available_virtual")

    def _search_incoming_qty(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_incoming")

    def _search_outgoing_qty(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_outgoing")

    def _search_free_qty(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_free")

    def _search_product_quantity(self, operator, value, field):
        op = PY_OPERATORS.get(operator)
        if op is None:
            records = self.with_context(prefetch_fields=False).search_fetch(
                [], [field], order="id"
            )
            positive_operator = Domain.NEGATIVE_OPERATORS.get(operator, operator)
            predicate = self._fields[field].filter_function(
                records, field, positive_operator, value
            )
            if positive_operator != operator:
                matched_records = records.filtered(lambda rec: not predicate(rec))
            else:
                matched_records = records.filtered(predicate)
            return [("id", "in", matched_records.ids)]
        location_domains = self._get_domain_locations()
        candidates = self._get_quantity_search_candidates(
            location_domains=location_domains
        )
        vals_by_product = candidates.with_context(
            prefetch_fields=False
        )._prepare_quantities_vals(
            self.env.context.get("lot_id"),
            self.env.context.get("owner_id"),
            self.env.context.get("package_id"),
            self.env.context.get("from_date", False),
            self.env.context.get("to_date", False),
            location_domains=location_domains,
        )
        matched = [
            product_id
            for product_id, vals in vals_by_product.items()
            if op(vals[field], value)
        ]
        if op(0.0, value):
            return ["|", ("id", "in", matched), ("id", "not in", candidates.ids)]
        return [("id", "in", matched)]

    def _search_qty_available_new(
        self, operator, value, lot_id=False, owner_id=False, package_id=False
    ):
        """Optimized method which doesn't search on stock.moves, only on stock.quants.

        Caller invariant: zero-matching searches (any `(operator, value)` that 0
        satisfies) are pre-routed to `_search_product_quantity` by
        `_search_qty_available`, so quant-less products — whose on-hand is 0 —
        can never match here and only products with quants need to be examined.
        """
        op = PY_OPERATORS.get(operator)
        if not op:
            return NotImplemented
        if isinstance(value, Iterable) and not isinstance(value, str):
            value = {float(v) for v in value}
        else:
            value = float(value)

        product_ids = set()
        domain_quant = self._get_domain_locations()[0]
        if lot_id:
            domain_quant &= Domain("lot_id", "=", lot_id)
        if owner_id:
            domain_quant &= Domain("owner_id", "=", owner_id)
        if package_id:
            domain_quant &= Domain("package_id", "=", package_id)
        quants_groupby = self.env["stock.quant"]._read_group(
            domain_quant, ["product_id"], ["quantity:sum"]
        )
        for product, quantity_sum in quants_groupby:
            if op(quantity_sum, value):
                product_ids.add(product.id)
        return list(product_ids)

    @api.onchange("tracking")
    def _onchange_tracking(self):
        if any(
            product.tracking != "none" and product.qty_available > 0 for product in self
        ):
            return {
                "warning": {
                    "title": _("Warning!"),
                    "message": _(
                        "You have product(s) in stock that have no lot/serial number. You can assign lot/serial numbers by doing an inventory adjustment."
                    ),
                }
            }
        return None

    def action_view_orderpoints(self):
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_orderpoint")
        context = action.get("context") or {}
        action["context"] = (
            literal_eval(context) if isinstance(context, str) else dict(context)
        )
        action["context"].pop("search_default_trigger", False)
        action["context"].update(
            {
                "search_default_filter_not_snoozed": True,
            },
        )
        if len(self) == 1:
            action["context"].update(
                {
                    "default_product_id": self.id,
                    "search_default_product_id": self.id,
                },
            )
        else:
            action["domain"] = Domain(action.get("domain") or Domain.TRUE) & Domain(
                "product_id", "in", self.ids
            )
        return action

    def action_view_stock_move_lines(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.stock_move_line_action"
        )
        action["domain"] = [("product_id", "=", self.id)]
        return action

    def action_view_related_putaway_rules(self):
        self.ensure_one()
        domain = [
            "|",
            ("product_id", "=", self.id),
            ("category_id", "=", self.product_tmpl_id.categ_id.id),
        ]
        return self.env["product.template"]._get_action_view_related_putaway_rules(
            domain
        )

    def action_view_storage_category_capacity(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_stock_storage_category_capacity"
        )
        action["context"] = {
            "hide_package_type": True,
        }
        if len(self) == 1:
            action["context"].update(
                {
                    "default_product_id": self.id,
                },
            )
        action["domain"] = [("product_id", "in", self.ids)]
        return action

    def preview_next_lot(self):
        """Interpolated preview of this product's next lot/serial value.

        Read-only single-RPC helper for the serial generator dialog: never
        consumes a sequence number (see ``ir.sequence.preview_next``).
        """
        self.ensure_one()
        sequence = self.lot_sequence_id
        return sequence.preview_next() if sequence else False

    def action_view_product_lot(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_stock_lot_form_2"
        )
        action["domain"] = [
            ("product_id", "=", self.id),
            *self.env["stock.lot"]._get_accessible_location_domain(),
        ]
        action["context"] = {
            "default_product_id": self.id,
            "set_product_readonly": True,
            "search_default_group_by_location": True,
        }
        return action

    def action_view_quants(self):
        multi_locations = self.env.user.has_group("stock.group_stock_multi_locations")
        context = {
            "hide_location": not multi_locations,
            "hide_lot": all(product.tracking == "none" for product in self),
            "no_at_date": True,
        }
        if self.env.user.has_group("stock.group_stock_manager"):
            context["inventory_mode"] = True
            if not multi_locations:
                warehouse = self.env["stock.warehouse"].search(
                    [("company_id", "=", self.env.company.id)], limit=1
                )
                if warehouse:
                    context["default_location_id"] = warehouse.lot_stock_id.id
        if len(self) == 1:
            context.update(default_product_id=self.id, single_product=True)
        else:
            context["product_tmpl_ids"] = self.product_tmpl_id.ids
        action = self.env["stock.quant"].with_context(**context).action_view_quants()
        if not self.env.context.get("is_stock_report"):
            action["domain"] = [("product_id", "in", self.ids)]
            action["name"] = _("Update Quantity")
        return action

    def action_product_forecast_report(self):
        self.ensure_one()
        return self.env["ir.actions.actions"]._for_xml_id(
            "stock.stock_forecasted_product_product_action"
        )

    @api.model
    def _normalize_quantities_to_date(self, to_date):
        """Normalize a ``to_date`` input to a datetime, and say whether it is past.

        A bare date -- or the ten-character string the web client sends for one --
        means "the whole of that day", so it widens to that day's last microsecond
        rather than to its midnight, which would drop the day's own moves.
        """
        original_value = to_date
        to_date = fields.Datetime.to_datetime(to_date)
        if (
            isinstance(original_value, date)
            and not isinstance(original_value, datetime)
        ) or (isinstance(original_value, str) and len(original_value) == 10):
            to_date = datetime.combine(to_date.date(), time.max)
        return to_date, bool(to_date and to_date < fields.Datetime.now())

    def _narrow_quantity_domains(
        self, quant, move_in, move_out, lot_id, owner_id, package_id
    ):
        """Apply the lot / owner / package scope to the quant and move domains.

        A table of triples rather than one domain applied three times, because each
        filter reads a different field on each side: a move carries its lot and its
        owner on its *lines*, its restricting partner on itself, and no package at all.

        ``None`` means "not filtered"; ``False`` is a real value and selects the
        records with no lot / owner / package -- which is why every test here is
        against ``None`` rather than truthiness.
        """
        if lot_id is not None:
            quant &= Domain([("lot_id", "=", lot_id)])
            move_in &= Domain([("move_line_ids.lot_id", "=", lot_id)])
            move_out &= Domain([("move_line_ids.lot_id", "=", lot_id)])
        if owner_id is not None:
            quant &= Domain([("owner_id", "=", owner_id)])
            move_in &= Domain([("restrict_partner_id", "=", owner_id)])
            move_out &= Domain([("restrict_partner_id", "=", owner_id)])
        if "owners" in self.env.context:
            owners = self.env.context["owners"]
            owner_leaf = ("in", owners) if owners else ("=", False)
            quant &= Domain([("owner_id", *owner_leaf)])
            move_in &= Domain([("move_line_ids.owner_id", *owner_leaf)])
            move_out &= Domain([("move_line_ids.owner_id", *owner_leaf)])
        if package_id is not None:
            quant &= Domain([("package_id", "=", package_id)])
        return quant, move_in, move_out

    def _prepare_quantities_scope(
        self,
        lot_id,
        owner_id,
        package_id,
        from_date=False,
        to_date=False,
        location_domains=None,
    ):
        """Assemble the domains one quantity computation reads, without querying.

        Split out of `_prepare_quantities_vals` so the scope can be asserted directly:
        it is the half that carries the lot/owner/package/date semantics, and it needs
        no database to be right.

        :param location_domains: the `_get_domain_locations` triple, when the caller
            has already resolved it. Resolving it costs a warehouse or location search,
            and a quantity *search* needs the very same triple to build its candidate
            set, so passing it through halves that work.
        :return: a `QuantityScope`.
        """
        domain_quant_loc, domain_move_in_loc, domain_move_out_loc = (
            location_domains or self._get_domain_locations()
        )
        product_domain = Domain([("product_id", "in", self.ids)])
        domain_quant = product_domain & domain_quant_loc
        to_date, dates_in_the_past = self._normalize_quantities_to_date(to_date)

        domain_move_in = product_domain & domain_move_in_loc
        domain_move_out = product_domain & domain_move_out_loc
        domain_quant, domain_move_in, domain_move_out = self._narrow_quantity_domains(
            domain_quant,
            domain_move_in,
            domain_move_out,
            lot_id,
            owner_id,
            package_id,
        )
        domain_move_in_done = domain_move_in
        domain_move_out_done = domain_move_out
        if from_date:
            date_domain_from = Domain([("date", ">=", from_date)])
            domain_move_in &= date_domain_from
            domain_move_out &= date_domain_from
        if to_date:
            date_domain_to = Domain([("date", "<=", to_date)])
            domain_move_in &= date_domain_to
            domain_move_out &= date_domain_to
        state_todo = Domain(
            [
                (
                    "state",
                    "in",
                    ("waiting", "confirmed", "assigned", "partially_available"),
                ),
            ]
        )
        expired_quant = self._expired_quant_domain(domain_quant, to_date)
        if dates_in_the_past:
            state_done_future = Domain([("state", "=", "done"), ("date", ">", to_date)])
            domain_move_in_done = state_done_future & domain_move_in_done
            domain_move_out_done = state_done_future & domain_move_out_done
        else:
            domain_move_in_done = domain_move_out_done = Domain.FALSE
        return QuantityScope(
            quant=domain_quant,
            expired_quant=expired_quant,
            move_in_todo=state_todo & domain_move_in,
            move_out_todo=state_todo & domain_move_out,
            move_in_done=domain_move_in_done,
            move_out_done=domain_move_out_done,
            dates_in_the_past=dates_in_the_past,
        )

    def _expired_quant_domain(self, domain_quant, to_date):
        """Narrow ``domain_quant`` to stock already expired at the cutoff.

        ``product_expiry`` opts in by setting ``with_expiration``; without it there is
        no expiry notion and this returns ``None`` -- deliberately not ``Domain.FALSE``,
        so "no expiry filter" stays distinguishable from "a filter matching nothing".

        The cutoff is the ``to_date`` *parameter*, not ``context['to_date']``. The two
        normally agree, because callers pass the context value straight through, but an
        override that rewrites the parameter -- ``purchase_stock`` does, for its demand
        suggestion -- must not be silently ignored here while every other window in the
        scope honours it. The parameter is also already normalised to a datetime, where
        the context still holds whatever the caller happened to set.
        """
        if not self.env.context.get("with_expiration"):
            return None
        max_date = (
            to_date
            if to_date and self.env.context.get("fresh_qty_forecast")
            else self.env.context["with_expiration"]
        )
        return domain_quant & Domain([("removal_date", "<=", max_date)])

    def _read_quantities(self, scope):
        """Run `scope`'s grouped reads. The only method here that touches the database."""
        Move = self.env["stock.move"]
        Quant = self.env["stock.quant"]
        moves_in_res = {
            product.id: product_qty
            for product, product_qty in Move._read_group(
                scope.move_in_todo,
                ["product_id"],
                ["product_qty:sum"],
            )
        }
        moves_out_res = {
            product.id: product_qty
            for product, product_qty in Move._read_group(
                scope.move_out_todo,
                ["product_id"],
                ["product_qty:sum"],
            )
        }
        quants_res = {
            product.id: (quantity, reserved_quantity)
            for product, quantity, reserved_quantity in Quant._read_group(
                scope.quant,
                ["product_id"],
                ["quantity:sum", "reserved_quantity:sum"],
            )
        }
        expired_unreserved_quants_res = {}
        if scope.expired_quant is not None:
            expired_unreserved_quants_res = {
                product.id: quantity - reserved_quantity
                for product, quantity, reserved_quantity in Quant._read_group(
                    scope.expired_quant,
                    ["product_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
            }
        moves_in_res_past = defaultdict(float)
        moves_out_res_past = defaultdict(float)
        if scope.dates_in_the_past:
            groupby = ["product_id", "product_uom_id"]
            past_in = Move._read_group(scope.move_in_done, groupby, ["quantity:sum"])
            past_out = Move._read_group(scope.move_out_done, groupby, ["quantity:sum"])
            for target, groups in (
                (moves_in_res_past, past_in),
                (moves_out_res_past, past_out),
            ):
                for product, uom, quantity in groups:
                    target[product.id] += uom._compute_quantity(
                        quantity,
                        product.uom_id,
                    )
        return QuantityReads(
            quants=quants_res,
            expired_unreserved=expired_unreserved_quants_res,
            moves_in=moves_in_res,
            moves_out=moves_out_res,
            moves_in_past=moves_in_res_past,
            moves_out_past=moves_out_res_past,
        )

    def _prepare_quantities_vals(
        self,
        lot_id,
        owner_id,
        package_id,
        from_date=False,
        to_date=False,
        location_domains=None,
    ):
        """Map each product id to its five quantity values.

        Three phases, each separately overridable: `_prepare_quantities_scope` decides
        *what* to read, `_read_quantities` reads it, and the loop below turns the raw
        sums into per-product, UoM-rounded values.

        Products with nothing to read need no special case: every lookup below defaults
        to zero, so they fall through the same arithmetic to the same five zeros a
        short-circuit would have written.
        """
        scope = self._prepare_quantities_scope(
            lot_id,
            owner_id,
            package_id,
            from_date=from_date,
            to_date=to_date,
            location_domains=location_domains,
        )
        reads = self._read_quantities(scope)
        res = {}

        for product in self.with_context(prefetch_fields=False):
            origin_product_id = product._origin.id
            product_id = product.id
            res[product_id] = {}
            quantity, reserved_quantity = reads.quants.get(
                origin_product_id, (0.0, 0.0)
            )
            qty_available = quantity
            if scope.dates_in_the_past:
                qty_available += reads.moves_out_past.get(
                    origin_product_id, 0.0
                ) - reads.moves_in_past.get(origin_product_id, 0.0)
            expired_unreserved_qty = reads.expired_unreserved.get(
                origin_product_id,
                0.0,
            )
            res[product_id]["qty_available"] = product.uom_id.round(qty_available)
            res[product_id]["qty_free"] = product.uom_id.round(
                qty_available - reserved_quantity - expired_unreserved_qty
            )
            res[product_id]["qty_incoming"] = product.uom_id.round(
                reads.moves_in.get(origin_product_id, 0.0),
            )
            res[product_id]["qty_outgoing"] = product.uom_id.round(
                reads.moves_out.get(origin_product_id, 0.0),
            )
            res[product_id]["qty_available_virtual"] = product.uom_id.round(
                qty_available
                + res[product_id]["qty_incoming"]
                - res[product_id]["qty_outgoing"]
                - expired_unreserved_qty,
            )

        return res

    def _get_quantity_search_candidates(self, location_domains=None):
        """Products whose on-hand/forecast quantity fields can be non-zero: those with
        quants or moves in the relevant locations.

        A superset is safe (extras compute to 0 and are filtered out) but a subset
        drops matches, so any override letting a product be non-zero without its own
        quants/moves (e.g. mrp phantom-BoM kits, sourced from components) MUST extend
        this set.

        The second consumer of that contract is the *complement*: a zero-matching search
        returns `("id", "not in", <these ids>)` for everything not examined. That is why
        the ids are materialised in Python rather than left as a subquery over quants and
        moves -- a subquery cannot see an override, so a stocked kit would fall into the
        complement and be matched by `qty_available <= 0`. Measured: the subquery form is
        ~13% faster and answers `True` there, where this one correctly answers `False`.

        :param location_domains: the `_get_domain_locations` triple, when the caller
            has already resolved it.
        """
        domain_quant_loc, domain_move_in_loc, domain_move_out_loc = (
            location_domains or self._get_domain_locations()
        )
        Quant = self.env["stock.quant"]
        Move = self.env["stock.move"]
        product_ids = {
            product.id
            for [product] in Quant._read_group(domain_quant_loc, ["product_id"])
        }
        product_ids |= {
            product.id
            for [product] in Move._read_group(
                domain_move_in_loc | domain_move_out_loc, ["product_id"]
            )
        }
        return self.env["product.product"].browse(product_ids)

    def _get_components(self):
        """The storable products this one resolves to. Itself, unless it is a kit.

        Returns a recordset: `mrp` overrides it to explode a phantom BoM, and the
        callers compare it against the product itself.
        """
        self.ensure_one()
        return self

    def _get_description(self, picking_type_id):
        """Outgoing pickings always use the product name; others use the product
        description if set, falling back to the name.
        """
        self.ensure_one()
        if picking_type_id.code == "outgoing":
            return self.display_name
        return (
            html2plaintext(self.description)
            if not is_html_empty(self.description)
            else self.display_name
        )

    def _get_picking_description(self, picking_type_id):
        """Return the receipt/delivery/internal description matching the picking type."""
        self.ensure_one()
        return {
            "incoming": self.description_pickingin,
            "outgoing": self.description_pickingout,
            "internal": self.description_picking,
        }.get(picking_type_id.code, "")

    def _get_total_routes(self):
        return self.env["stock.route"]

    def _resolve_context_record_ids(self, model, values) -> set[int]:
        """Resolve context values -- ids, names to match, or a mix -- to existing ids.

        See `_get_domain_locations` for why booleans raise and why missing ids are
        dropped rather than allowed to reach a `browse`.
        """
        Model = self.env[model]
        ids = set()
        domains = []
        for item in values:
            if isinstance(item, bool):
                raise ValueError(
                    f"Invalid {model!r} value {item!r} in the context: "
                    f"expected a database id or a name to search for.",
                )
            if isinstance(item, int):
                ids.add(item)
            else:
                domains.append(Domain(Model._rec_name, "ilike", item))
        if domains:
            ids |= set(Model.search(Domain.OR(domains)).ids)
        existing = set(Model.browse(ids).exists().ids)
        if missing := ids - existing:
            _logger.warning(
                "Ignoring %s id(s) %s from the context: no such record.",
                model,
                sorted(missing),
            )
        return existing

    def _get_domain_locations(self):
        """Resolve the 'location'/'search_location' and 'warehouse_id'/'search_warehouse'
        context keys into location domains; falls back to all stock locations of the
        current companies' warehouses when none are given.

        Each key takes an id, a name to match, or a list of either. Two input rules are
        load-bearing, because these values arrive from a context nobody validates:

        - A boolean is rejected outright. ``isinstance(True, int)`` holds, so an
          unguarded int test lets it through to the recursive CTE as ``id = ANY(true)``,
          which Postgres answers with a raw ``UndefinedFunction: operator does not
          exist: integer = boolean``.
        - Ids that no longer exist are dropped, with a warning. That keeps every
          unresolvable filter on one path -- an empty scope, hence zero quantities --
          instead of a ``MissingError`` from whichever branch dereferences the browsed
          record first, which is what made a stale id silent alone but fatal alongside
          ``warehouse_id``.
        """
        location_ids = self._scope_location_ids()
        if location_ids is None:
            location_ids = set(
                self.env["stock.warehouse"]
                .search([("company_id", "in", self.env.companies.ids)])
                .mapped("view_location_id")
                .ids
            )
        return self._get_domain_locations_new(location_ids)

    def _scope_location_ids(self) -> set[int] | None:
        """The locations the context scopes quantities to, or ``None`` for no scope.

        Split out of `_get_domain_locations` because the *write* half of
        `qty_available` needs the same answer: a scope the compute honours has to be a
        scope the inverse honours, or the field does not round-trip. Returning ``None``
        rather than the default set keeps "the caller asked for nothing" distinguishable
        from "the caller asked for every warehouse", which is the distinction
        `_resolve_inventory_location` turns on.
        """
        Location = self.env["stock.location"]
        Warehouse = self.env["stock.warehouse"]
        _search_ids = self._resolve_context_record_ids

        location = self.env.context.get("location") or self.env.context.get(
            "search_location"
        )
        if location and not isinstance(location, list):
            location = [location]
        warehouse = self.env.context.get("warehouse_id") or self.env.context.get(
            "search_warehouse"
        )
        if warehouse and not isinstance(warehouse, list):
            warehouse = [warehouse]
        if warehouse:
            w_ids = set(
                Warehouse.browse(_search_ids("stock.warehouse", warehouse))
                .mapped("view_location_id")
                .ids
            )
            if not location:
                return w_ids
            l_ids = _search_ids("stock.location", location)
            parents = Location.browse(w_ids).mapped("parent_path")
            return {
                loc.id
                for loc in Location.browse(l_ids)
                if any(loc.parent_path.startswith(parent) for parent in parents)
            }
        if location:
            return _search_ids("stock.location", location)
        return None

    def _get_domain_locations_new(self, location_ids) -> tuple[Domain, Domain, Domain]:
        """Return (quant, move-in, move-out) domains for a set of locations.

        ``strict`` matches the given locations exactly; otherwise the scope widens to
        their descendants, via a recursive CTE rather than an ``id`` list, so the
        location tree is not materialised into the outer query.

        ``skip_in_progress`` drops the ``location_final_id`` reasoning that treats a
        not-yet-done move by where it will end up. It is a no-op under ``strict`` **by
        construction, not by omission**: the strict branch never introduces that
        reasoning, so its ordinary return is already the tuple the shortcut builds.
        Pinned by ``test_strict_scope_already_skips_in_progress``.
        """
        if not location_ids:
            return (Domain.FALSE,) * 3
        locations = self.env["stock.location"].browse(location_ids)
        if self.env.context.get("strict"):
            loc_domain = Domain("location_id", "in", locations.ids)
            dest_loc_domain = Domain("location_dest_id", "in", locations.ids)
            dest_loc_domain_out = Domain("location_dest_id", "not in", locations.ids)
            return (
                loc_domain,
                dest_loc_domain & ~loc_domain,
                loc_domain & dest_loc_domain_out,
            )

        descendants = self._descendant_locations_query(locations)
        loc_domain = Domain("location_id", "in", descendants)
        dest_loc_domain_done = Domain("location_dest_id", "in", descendants)
        if self.env.context.get("skip_in_progress"):
            return (
                loc_domain,
                dest_loc_domain_done & ~loc_domain,
                loc_domain & ~dest_loc_domain_done,
            )
        dest_loc_domain_in_progress = Domain(
            [
                "|",
                "&",
                ("location_final_id", "!=", False),
                ("location_final_id", "in", descendants),
                "&",
                ("location_final_id", "=", False),
                ("location_dest_id", "in", descendants),
            ],
        )
        dest_loc_domain = Domain(
            [
                "|",
                "&",
                ("state", "=", "done"),
                dest_loc_domain_done,
                "&",
                ("state", "!=", "done"),
                dest_loc_domain_in_progress,
            ],
        )
        dest_loc_domain_out = Domain(
            [
                "|",
                "&",
                ("state", "=", "done"),
                ~dest_loc_domain_done,
                "&",
                ("state", "!=", "done"),
                ~dest_loc_domain_in_progress,
            ],
        )
        return (
            loc_domain,
            dest_loc_domain & ~loc_domain,
            loc_domain & dest_loc_domain_out,
        )

    def _descendant_locations_query(self, locations) -> Query:
        """A subquery yielding ``locations`` and everything below them.

        A recursive CTE rather than resolving the tree in Python: the alternative is a
        ``child_of`` that searches the children and injects every id into the outer
        query.
        """
        return Query(
            locations.env,
            "descendants",
            SQL(
                """
                (
                    WITH RECURSIVE descendants AS (
                        SELECT id
                        FROM stock_location
                        WHERE id = ANY(%s)

                        UNION

                        SELECT sl.id
                        FROM stock_location sl
                        JOIN descendants d
                            ON sl.location_id = d.id
                    )
                    SELECT id FROM descendants
                )
                """,
                list(locations.ids),
            ),
        )

    def _get_quantity_in_progress(self, location_ids=False, warehouse_ids=False):
        return defaultdict(float), defaultdict(float)

    def _get_rules_from_location(self, location, route_ids=False, seen_rules=False):
        if not seen_rules:
            seen_rules = self.env["stock.rule"]
        warehouse = location.warehouse_id
        rule = (
            self.env["stock.rule"]
            .with_context(active_test=True)
            ._get_rule(
                self,
                location,
                {
                    "route_ids": route_ids,
                    "warehouse_id": warehouse,
                },
            )
        )
        if rule in seen_rules:
            raise UserError(
                _(
                    "Invalid rule's configuration, the following rule causes an endless loop: %s",
                    rule.display_name,
                ),
            )
        if not rule:
            return seen_rules
        if rule.procure_method == "make_to_stock" or rule.action not in (
            "pull_push",
            "pull",
        ):
            return seen_rules | rule
        else:
            return self._get_rules_from_location(
                rule.location_src_id, seen_rules=seen_rules | rule
            )

    def _get_dates_info(self, date_planned, location, route_ids=False):
        rules = self._get_rules_from_location(location, route_ids=route_ids)
        delays, __ = rules.with_context(bypass_delay_description=True)._get_lead_days(
            self
        )
        return {
            "date_planned": date_planned,
            "date_order": date_planned - relativedelta(days=delays["purchase_delay"]),
        }

    @api.model
    def _count_returned_sn_products(self, sn_lot):
        domain = self._count_returned_sn_products_domain(sn_lot, or_domains=[])
        if not domain:
            return 0
        return self.env["stock.move.line"].search_count(domain)

    @api.model
    def _count_returned_sn_products_domain(self, sn_lot, or_domains):
        if not or_domains:
            return None
        return Domain(
            [
                ("lot_id", "=", sn_lot.id),
                ("quantity", "=", 1),
                ("state", "=", "done"),
            ]
        ) & Domain.OR(or_domains)

    def _restamp_uom(self, model, to_uom_id):
        """Point every ``model`` record of these products at ``to_uom_id``.

        Restamping is only meaningful while each record still carries the product's
        current UoM -- the quantities are not converted -- so anything already recorded
        in a different unit aborts the change.

        The unit being left is read from the *template*, never from ``product.uom_id``.
        `product.template.write` calls this before writing itself, so the template still
        holds the old unit -- but assigning on a **variant** goes through the related
        field, and the ORM has already put the new unit in the variant's cache by the
        time it determines that inverse. Read from the variant, the guard compared every
        existing record against the unit being moved *to*, so it fired on the one case it
        exists to allow: `product.uom_id = new` raised for any product with a single move
        while `product.product_tmpl_id.uom_id = new` restamped it and passed. Same read as
        `base_order._update_uom_on_order_lines`, which is this method for order lines.
        """
        for uom, product, records in self.env[model]._read_group(
            [("product_id", "in", self.ids)],
            ["product_uom_id", "product_id"],
            ["id:recordset"],
        ):
            if uom != product.product_tmpl_id.uom_id:
                raise UserError(
                    _(
                        "As other units of measure (ex : %(problem_uom)s) "
                        "than %(uom)s have already been used for this product, the change of unit of measure can not be done."
                        "If you want to change it, please archive the product and create a new one.",
                        problem_uom=uom.name,
                        uom=product.product_tmpl_id.uom_id.name,
                    ),
                )
            records.product_uom_id = to_uom_id

    def _update_uom(self, to_uom_id):
        self._restamp_uom("stock.move", to_uom_id)
        self._restamp_uom("stock.move.line", to_uom_id)
        return super()._update_uom(to_uom_id)

    def _filter_to_unlink(self):
        """Exclude products the database will refuse to delete.

        `_unlink_or_archive` recovers from a refusal -- it retries inside a savepoint
        and halves the batch -- so missing one here costs correctness nothing. It costs
        query count: a single blocked product turns one statement into a binary search
        over the batch. `stock.quant.product_id` and `stock.move.product_id` both
        restrict on delete, and having stock history is the norm rather than the
        exception, so both belong here alongside lots.

        Only the lot read needs `active_test=False`, and it genuinely needs it: an
        archived lot still restricts the delete. Quants and moves carry no `active`
        field, so the key would be a no-op there.
        """
        domain = [("product_id", "in", self.ids)]
        grouped = (
            self.env["stock.lot"]
            .with_context(active_test=False)
            ._read_group(domain, ["product_id"]),
            self.env["stock.quant"]._read_group(domain, ["product_id"]),
            self.env["stock.move"]._read_group(domain, ["product_id"]),
        )
        linked_product_ids = {product.id for groups in grouped for [product] in groups}
        return super(
            ProductProduct, self - self.browse(linked_product_ids)
        )._filter_to_unlink()

    def _get_allowed_uoms(self):
        """UoMs selectable for this product: its own UoM, its packaging UoMs,
        and its vendors' purchase UoMs. Single source for the scrap and
        replenish wizards' ``allowed_uom_ids`` computes."""
        return self.uom_id | self.uom_ids | self.seller_ids.product_uom_id

    def _trigger_uom_warning(self):
        res = super()._trigger_uom_warning()
        if res:
            return res
        moves = (
            self.env["stock.move"]
            .sudo()
            .search_count([("product_id", "in", self.ids)], limit=1)
        )
        return bool(moves)
