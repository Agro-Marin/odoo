import operator as py_operator
from ast import literal_eval
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.libs.barcode import check_barcode_encoding
from odoo.libs.numbers.float_utils import float_compare
from odoo.tools import SQL, Query
from odoo.tools.mail import html2plaintext, is_html_empty

PY_OPERATORS = {
    "<": py_operator.lt,
    ">": py_operator.gt,
    "<=": py_operator.le,
    ">=": py_operator.ge,
    "=": py_operator.eq,
    "!=": py_operator.ne,
    "in": lambda elem, container: elem in container,
    "not in": lambda elem, container: elem not in container,
}


class ProductProduct(models.Model):
    _inherit = "product.product"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    stock_quant_ids = fields.One2many(
        comodel_name="stock.quant",
        inverse_name="product_id",
    )
    stock_move_ids = fields.One2many(
        comodel_name="stock.move",
        inverse_name="product_id",
    )  # dependency of _compute_quantities
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
        string="Free To Use Quantity ",
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

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

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
        res = super().fields_get(allfields, attributes)
        context_location = self.env.context.get("location") or self.env.context.get(
            "search_location",
        )
        if context_location and isinstance(context_location, int):
            location = self.env["stock.location"].browse(context_location)
            # Relabel the on-hand/forecast fields to match what they mean at a location
            # of the given usage (e.g. at a supplier location, on-hand is "Received Qty").
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

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

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

    def _compute_count_moves(self):
        # `picking_code` is a non-stored related field, usable in a domain but not as a
        # `_read_group` groupby, so incoming/outgoing need separate grouped reads. They
        # still share a single "now" reference for a consistent 12-month window.
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

    @api.depends("product_tmpl_id")
    def _compute_show_qty_status_button(self):
        for product in self:
            product.show_on_hand_qty_status_button = (
                product.product_tmpl_id.show_on_hand_qty_status_button
            )
            product.show_forecasted_qty_status_button = (
                product.product_tmpl_id.show_forecasted_qty_status_button
            )

    @api.depends("product_tmpl_id")
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
        "package_id",
        "from_date",
        "to_date",
        "location",
        "warehouse_id",
        "allowed_company_ids",
        "is_storable",
    )
    @api.depends(
        "stock_move_ids.product_qty", "stock_move_ids.state", "stock_move_ids.quantity"
    )
    def _compute_quantities(self):
        products = (
            self.with_context(prefetch_fields=False)
            .filtered(lambda p: p.type != "service")
            .with_context(prefetch_fields=True)
        )
        res = products._prepare_quantities_vals(
            self.env.context.get("lot_id"),
            self.env.context.get("owner_id"),
            self.env.context.get("package_id"),
            self.env.context.get("from_date"),
            self.env.context.get("to_date"),
        )
        # Services have 0 quantities and are absent from res; zero every field first so
        # they, and the zeros the `if val` filter drops below, are still set.
        self.with_context(skip_qty_available_update=True).qty_available = 0.0
        self.qty_incoming = 0.0
        self.qty_outgoing = 0.0
        self.qty_available_virtual = 0.0
        self.qty_free = 0.0
        for product in products:
            product.with_context(skip_qty_available_update=True).update(
                {key: val for key, val in res[product.id].items() if val}
            )

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _inverse_qty_available(self):
        """Allow manually adjusting qty_available from the product form by applying an
        inventory adjustment at the default warehouse; skipped when the write comes from
        _compute_quantities itself.
        """
        if self.env.context.get("skip_qty_available_update", False):
            return
        # The target warehouse only depends on the current company, so resolve it once
        # instead of searching per product.
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        for product in self:
            if (
                product.type == "consu"
                and product.is_storable
                and float_compare(
                    product.qty_available,
                    0.0,
                    precision_rounding=product.uom_id.rounding,
                )
                >= 0
            ):
                self.env["stock.quant"].with_context(
                    inventory_mode=True, from_inverse_qty=True
                ).create(
                    {
                        "product_id": product.id,
                        "location_id": warehouse.lot_stock_id.id,
                        "inventory_quantity": product.qty_available,
                    }
                )._apply_inventory()

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_qty_available(self, operator, value):
        # Without a date range, qty_available depends only on quants, not moves,
        # so use the faster quant-only '_search_qty_available_new' instead of
        # '_search_product_quantity'.
        if not ({"from_date", "to_date"} & self.env.context.keys()):
            product_ids = self._search_qty_available_new(
                operator,
                value,
                self.env.context.get("lot_id"),
                self.env.context.get("owner_id"),
                self.env.context.get("package_id"),
            )
            # `_search_qty_available_new` returns NotImplemented for operators it can't
            # handle on quants alone (e.g. `like`); fall back to the move-aware path.
            if product_ids is not NotImplemented:
                return [("id", "in", product_ids)]
        return self._search_product_quantity(operator, value, "qty_available")

    def _search_virtual_available(self, operator, value):
        # TDE FIXME: should probably clean the search methods
        return self._search_product_quantity(operator, value, "qty_available_virtual")

    def _search_incoming_qty(self, operator, value):
        # TDE FIXME: should probably clean the search methods
        return self._search_product_quantity(operator, value, "qty_incoming")

    def _search_outgoing_qty(self, operator, value):
        # TDE FIXME: should probably clean the search methods
        return self._search_product_quantity(operator, value, "qty_outgoing")

    def _search_free_qty(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_free")

    def _search_product_quantity(self, operator, value, field):
        op = PY_OPERATORS.get(operator)
        if op is None:
            # Operators the candidate-set path can't evaluate (e.g. `like`): fall back to
            # computing the field for every product and filtering in memory. Order on `id`
            # to avoid the default (name) order, which slows the underlying search down.
            ids = (
                self.with_context(prefetch_fields=False)
                .search_fetch([], [field], order="id")
                .filtered_domain([(field, operator, value)])
                .ids
            )
            return [("id", "in", ids)]
        # Only products with quants or moves (kits aside) can be non-zero; the rest
        # are 0. Compute those candidates via the override-aware compute; every other
        # product is treated as 0 in the `not in` branch below, skipping a full compute.
        candidates = self._get_quantity_search_candidates()
        vals_by_product = candidates.with_context(
            prefetch_fields=False
        )._prepare_quantities_vals(
            self.env.context.get("lot_id"),
            self.env.context.get("owner_id"),
            self.env.context.get("package_id"),
            self.env.context.get("from_date", False),
            self.env.context.get("to_date", False),
        )
        matched = [
            product_id
            for product_id, vals in vals_by_product.items()
            if op(vals[field], value)
        ]
        if op(0.0, value):
            # Products outside the candidate set have a value of 0, so they match iff 0 does.
            return ["|", ("id", "in", matched), ("id", "not in", candidates.ids)]
        return [("id", "in", matched)]

    def _search_qty_available_new(
        self, operator, value, lot_id=False, owner_id=False, package_id=False
    ):
        """Optimized method which doesn't search on stock.moves, only on stock.quants."""
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

        # Products with no quants at all are only relevant if 0 matches the search value.
        include_zero = op(0.0, value)

        processed_product_ids = set()
        for product, quantity_sum in quants_groupby:
            product_id = product.id
            if include_zero:
                processed_product_ids.add(product_id)
            if op(quantity_sum, value):
                product_ids.add(product_id)

        if include_zero:
            # A product absent from the quant groups has 0 on hand in this domain,
            # so it matches whenever 0 does — regardless of `is_storable`. Filtering
            # to storable here would diverge from the field's `filtered_domain`
            # semantics and the dated search, dropping non-storable/service products
            # that legitimately have 0.
            products_without_quants_in_domain = self.env["product.product"].search(
                [("id", "not in", list(processed_product_ids))],
                order="id",
            )
            product_ids |= set(products_without_quants_in_domain.ids)
        return list(product_ids)

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_view_orderpoints(self):
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_orderpoint")
        action["context"] = literal_eval(action.get("context"))
        action["context"].pop("search_default_trigger", False)
        action["context"].update(
            {
                "search_default_filter_not_snoozed": True,
            },
        )
        if self and len(self) == 1:
            action["context"].update(
                {
                    "default_product_id": self.ids[0],
                    "search_default_product_id": self.ids[0],
                },
            )
        else:
            action["domain"] = Domain(action.get("domain") or Domain.TRUE) & Domain(
                "product_id", "in", self.ids
            )
        return action

    def action_view_routes(self):
        return self.mapped("product_tmpl_id").action_view_routes()

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

    def action_view_product_lot(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_stock_lot_form_2"
        )
        action["domain"] = [
            ("product_id", "=", self.id),
            "|",
            ("location_id", "=", False),
            (
                "location_id",
                "any",
                self.env["stock.location"]._check_company_domain(
                    self.env.context["allowed_company_ids"]
                ),
            ),
        ]
        action["context"] = {
            "default_product_id": self.id,
            "set_product_readonly": True,
            "search_default_group_by_location": True,
        }
        return action

    # A method of the same name exists on product.template, but it just dispatches to the variants.
    def action_view_quants(self):
        hide_location = not self.env.user.has_group("stock.group_stock_multi_locations")
        hide_lot = all(product.tracking == "none" for product in self)
        self = self.with_context(
            hide_location=hide_location,
            hide_lot=hide_lot,
            no_at_date=True,
        )

        # inventory_mode makes the quant view editable, reserved to stock managers.
        if self.env.user.has_group("stock.group_stock_manager"):
            self = self.with_context(inventory_mode=True)
            if not self.env.user.has_group("stock.group_stock_multi_locations"):
                user_company = self.env.company
                warehouse = self.env["stock.warehouse"].search(
                    [("company_id", "=", user_company.id)], limit=1
                )
                if warehouse:
                    self = self.with_context(
                        default_location_id=warehouse.lot_stock_id.id
                    )
        if len(self) == 1:
            self = self.with_context(default_product_id=self.id, single_product=True)
        else:
            self = self.with_context(product_tmpl_ids=self.product_tmpl_id.ids)
        action = self.env["stock.quant"].action_view_quants()
        # note that this action is used by different views w/varying customizations
        if not self.env.context.get("is_stock_report"):
            action["domain"] = [("product_id", "in", self.ids)]
            action["name"] = _("Update Quantity")
        return action

    def action_product_forecast_report(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.stock_forecasted_product_product_action"
        )
        return action

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _prepare_quantities_vals(
        self,
        lot_id,
        owner_id,
        package_id,
        from_date=False,
        to_date=False,
    ):
        domain_quant_loc, domain_move_in_loc, domain_move_out_loc = (
            self._get_domain_locations()
        )
        product_domain = Domain([("product_id", "in", self.ids)])
        domain_quant = product_domain & domain_quant_loc
        dates_in_the_past = False
        # Only to_date needs this date-vs-datetime distinction: it is the point in time
        # for which qty_available is reconstructed; from_date is just a range filter.
        original_value = to_date
        to_date = fields.Datetime.to_datetime(to_date)
        if (
            isinstance(original_value, date)
            and not isinstance(original_value, datetime)
        ) or (isinstance(original_value, str) and len(original_value) == 10):
            to_date = datetime.combine(to_date.date(), time.max)
        if to_date and to_date < fields.Datetime.now():
            dates_in_the_past = True

        domain_move_in = product_domain & domain_move_in_loc
        domain_move_out = product_domain & domain_move_out_loc
        if lot_id is not None:
            domain_quant &= Domain([("lot_id", "=", lot_id)])
            domain_move_in &= Domain([("move_line_ids.lot_id", "=", lot_id)])
            domain_move_out &= Domain([("move_line_ids.lot_id", "=", lot_id)])
        if owner_id is not None:
            domain_quant &= Domain([("owner_id", "=", owner_id)])
            domain_move_in &= Domain([("restrict_partner_id", "=", owner_id)])
            domain_move_out &= Domain([("restrict_partner_id", "=", owner_id)])
        if "owners" in self.env.context:
            owners = self.env.context["owners"]
            if owners:
                domain_quant &= Domain([("owner_id", "in", self.env.context["owners"])])
            else:
                domain_quant &= Domain([("owner_id", "=", False)])
        if package_id is not None:
            domain_quant &= Domain([("package_id", "=", package_id)])
        if dates_in_the_past:
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
        Move = self.env["stock.move"].with_context(active_test=False)
        Quant = self.env["stock.quant"].with_context(active_test=False)
        state_todo = Domain(
            [
                (
                    "state",
                    "in",
                    ("waiting", "confirmed", "assigned", "partially_available"),
                ),
            ]
        )
        domain_move_in_todo = state_todo & domain_move_in
        domain_move_out_todo = state_todo & domain_move_out
        moves_in_res = {
            product.id: product_qty
            for product, product_qty in Move._read_group(
                domain_move_in_todo,
                ["product_id"],
                ["product_qty:sum"],
            )
        }
        moves_out_res = {
            product.id: product_qty
            for product, product_qty in Move._read_group(
                domain_move_out_todo,
                ["product_id"],
                ["product_qty:sum"],
            )
        }
        quants_res = {
            product.id: (quantity, reserved_quantity)
            for product, quantity, reserved_quantity in Quant._read_group(
                domain_quant,
                ["product_id"],
                ["quantity:sum", "reserved_quantity:sum"],
            )
        }
        expired_unreserved_quants_res = {}
        if self.env.context.get("with_expiration"):
            max_date = (
                self.env.context["to_date"]
                if self.env.context.get("to_date")
                and self.env.context.get("fresh_qty_forecast")
                else self.env.context["with_expiration"]
            )
            domain_quant &= Domain([("removal_date", "<=", max_date)])
            expired_unreserved_quants_res = {
                product.id: quantity - reserved_quantity
                for product, quantity, reserved_quantity in Quant._read_group(
                    domain_quant,
                    ["product_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
            }
        moves_in_res_past = defaultdict(float)
        moves_out_res_past = defaultdict(float)
        if dates_in_the_past:
            # Reconstruct the qty at to_date by reversing the moves done between
            # to_date and now, rather than replaying history from to_date forward.
            state_done_future = Domain(
                [
                    ("state", "=", "done"),
                    ("date", ">", to_date),
                ]
            )
            domain_move_in_done = state_done_future & domain_move_in_done
            domain_move_out_done = state_done_future & domain_move_out_done

            groupby = ["product_id", "product_uom"]
            for product, uom, quantity in Move._read_group(
                domain_move_in_done,
                groupby,
                ["quantity:sum"],
            ):
                moves_in_res_past[product.id] += uom._compute_quantity(
                    quantity,
                    product.uom_id,
                )

            for product, uom, quantity in Move._read_group(
                domain_move_out_done,
                groupby,
                ["quantity:sum"],
            ):
                moves_out_res_past[product.id] += uom._compute_quantity(
                    quantity,
                    product.uom_id,
                )

        res = dict()

        for product in self.with_context(prefetch_fields=False):
            origin_product_id = product._origin.id
            product_id = product.id
            if not origin_product_id or (
                origin_product_id not in quants_res
                and origin_product_id not in moves_in_res
                and origin_product_id not in moves_out_res
                and origin_product_id not in moves_in_res_past
                and origin_product_id not in moves_out_res_past
                and origin_product_id not in expired_unreserved_quants_res
            ):
                res[product_id] = dict.fromkeys(
                    [
                        "qty_available",
                        "qty_free",
                        "qty_incoming",
                        "qty_outgoing",
                        "qty_available_virtual",
                    ],
                    0.0,
                )
                continue
            res[product_id] = {}
            quantity, reserved_quantity = quants_res.get(origin_product_id, (0.0, 0.0))
            if dates_in_the_past:
                qty_available = (
                    quantity
                    - moves_in_res_past.get(origin_product_id, 0.0)
                    + moves_out_res_past.get(origin_product_id, 0.0)
                )
            else:
                qty_available = quantity
            expired_unreserved_qty = expired_unreserved_quants_res.get(
                origin_product_id,
                0.0,
            )
            res[product_id]["qty_available"] = product.uom_id.round(qty_available)
            res[product_id]["qty_free"] = product.uom_id.round(
                qty_available - reserved_quantity - expired_unreserved_qty
            )
            res[product_id]["qty_incoming"] = product.uom_id.round(
                moves_in_res.get(origin_product_id, 0.0),
            )
            res[product_id]["qty_outgoing"] = product.uom_id.round(
                moves_out_res.get(origin_product_id, 0.0),
            )
            res[product_id]["qty_available_virtual"] = product.uom_id.round(
                qty_available
                + res[product_id]["qty_incoming"]
                - res[product_id]["qty_outgoing"]
                - expired_unreserved_qty,
            )

        return res

    def _get_quantity_search_candidates(self):
        """Products whose on-hand/forecast quantity fields can be non-zero: those with
        quants or moves in the relevant locations.

        A superset is safe (extras compute to 0 and are filtered out) but a subset
        drops matches, so any override letting a product be non-zero without its own
        quants/moves (e.g. mrp phantom-BoM kits, sourced from components) MUST extend
        this set.
        """
        domain_quant_loc, domain_move_in_loc, domain_move_out_loc = (
            self._get_domain_locations()
        )
        Quant = self.env["stock.quant"].with_context(active_test=False)
        Move = self.env["stock.move"].with_context(active_test=False)
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

    def get_components(self):
        self.ensure_one()
        return self.ids

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
        return {
            "incoming": self.description_pickingin,
            "outgoing": self.description_pickingout,
            "internal": self.description_picking,
        }.get(picking_type_id.code, "")

    def get_total_routes(self):
        # No routes by default; overridden by other modules (e.g. purchase, mrp) to add theirs.
        return self.env["stock.route"]

    def _get_domain_locations(self):
        """Resolve the 'location'/'search_location' and 'warehouse_id'/'search_warehouse'
        context keys into location domains; falls back to all stock locations of the
        current companies' warehouses when none are given.
        """
        Location = self.env["stock.location"]
        Warehouse = self.env["stock.warehouse"]

        def _search_ids(model, values):
            ids = set()
            domains = []
            for item in values:
                if isinstance(item, int):
                    ids.add(item)
                else:
                    domains.append(Domain(self.env[model]._rec_name, "ilike", item))
            if domains:
                ids |= set(self.env[model].search(Domain.OR(domains)).ids)
            return ids

        # location/warehouse may come from python code (single value) or search view
        # dummy fields (list); normalize to a list either way.
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
            if location:
                l_ids = _search_ids("stock.location", location)
                parents = Location.browse(w_ids).mapped("parent_path")
                location_ids = {
                    loc.id
                    for loc in Location.browse(l_ids)
                    if any(loc.parent_path.startswith(parent) for parent in parents)
                }
            else:
                location_ids = w_ids
        else:
            if location:
                location_ids = _search_ids("stock.location", location)
            else:
                location_ids = set(
                    Warehouse.search([("company_id", "in", self.env.companies.ids)])
                    .mapped("view_location_id")
                    .ids
                )

        return self._get_domain_locations_new(location_ids)

    def _get_domain_locations_new(self, location_ids) -> tuple[Domain, Domain, Domain]:
        if not location_ids:
            return (Domain.FALSE,) * 3
        locations = self.env["stock.location"].browse(location_ids)
        if self.env.context.get("strict"):
            loc_domain = Domain("location_id", "in", locations.ids)
            dest_loc_domain = Domain("location_dest_id", "in", locations.ids)
            dest_loc_domain_out = Domain("location_dest_id", "not in", locations.ids)
        elif locations:
            # Resolve the location subtree with a recursive CTE instead of a
            # `parent_path LIKE` scan: the LIKE form forces a sequential scan of
            # stock_location (no usable index), which is costly with many moves.
            descendants_query = Query(
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
            loc_domain = Domain("location_id", "in", descendants_query)
            # The condition should be split for done and not-done moves as the location_final_id only makes
            # sense for the part of the move chain that is not done yet.
            dest_loc_domain_done = Domain("location_dest_id", "in", descendants_query)
            dest_loc_domain_in_progress = Domain(
                [
                    "|",
                    "&",
                    ("location_final_id", "!=", False),
                    ("location_final_id", "in", descendants_query),
                    "&",
                    ("location_final_id", "=", False),
                    ("location_dest_id", "in", descendants_query),
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

            if self.env.context.get("skip_in_progress"):
                return (
                    loc_domain,
                    dest_loc_domain_done & ~loc_domain,
                    loc_domain & ~dest_loc_domain_done,
                )

        # returns: (domain_quant_loc, domain_move_in_loc, domain_move_out_loc)
        return (
            loc_domain,
            dest_loc_domain & ~loc_domain,
            loc_domain & dest_loc_domain_out,
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

    def _get_dates_info(self, date, location, route_ids=False):
        rules = self._get_rules_from_location(location, route_ids=route_ids)
        delays, _ = rules.with_context(bypass_delay_description=True)._get_lead_days(
            self
        )
        return {
            "date_planned": date,
            "date_order": date - relativedelta(days=delays["purchase_delay"]),
        }

    def _get_only_qty_available(self):
        """Equivalent to reading qty_available, but skips the read_group on moves
        needed for the other quantity fields.
        """
        domain_quant = Domain.AND(
            [self._get_domain_locations()[0], [("product_id", "in", self.ids)]]
        )
        quants_groupby = self.env["stock.quant"]._read_group(
            domain_quant,
            ["product_id"],
            ["quantity:sum"],
        )
        currents = defaultdict(float)
        currents.update({product.id: quantity for product, quantity in quants_groupby})
        return currents

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

    def _update_uom(self, to_uom_id):
        for uom, product, moves in self.env["stock.move"]._read_group(
            [("product_id", "in", self.ids)],
            ["product_uom", "product_id"],
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
            moves.product_uom = to_uom_id

        for uom, product, move_lines in self.env["stock.move.line"]._read_group(
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
            move_lines.product_uom_id = to_uom_id
        return super()._update_uom(to_uom_id)

    def _filter_to_unlink(self):
        domain = [("product_id", "in", self.ids)]
        lines = self.env["stock.lot"]._read_group(domain, ["product_id"])
        linked_product_ids = [product.id for [product] in lines]
        return super(
            ProductProduct, self - self.browse(linked_product_ids)
        )._filter_to_unlink()

    def filter_has_routes(self):
        """Return products with route_ids or whose categ_id has total_route_ids."""
        return self.filtered(
            lambda product: product.route_ids or product.categ_id.total_route_ids
        )

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
