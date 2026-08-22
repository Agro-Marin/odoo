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
    quant: Domain
    expired_quant: Domain | None
    move_in_todo: Domain
    move_out_todo: Domain
    move_in_done: Domain
    move_out_done: Domain
    dates_in_the_past: bool


class QuantityReads(NamedTuple):
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
        search="_search_qty_available_virtual",
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
        search="_search_qty_free",
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
        search="_search_qty_incoming",
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
        search="_search_qty_outgoing",
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
        "strict",
        "skip_in_progress",
        "with_expiration",
        "fresh_qty_forecast",
    )
    @api.depends(
        "stock_move_ids.product_qty", "stock_move_ids.state", "stock_move_ids.quantity"
    )
    def _compute_quantities(self):
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
        if self.env.context.get("skip_qty_available_update", False):
            return
        self._apply_qty_available([product.qty_available for product in self])

    def _apply_qty_available(self, quantities):
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
        location_ids = self._scope_location_ids()
        if location_ids is None:
            return self.env["stock.location"].browse()
        locations = self.env["stock.location"].browse(location_ids)
        warehouses = locations.warehouse_id
        if len(locations) == 1 and locations.usage == "internal":
            return locations
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

    def _search_qty_available_virtual(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_available_virtual")

    def _search_qty_incoming(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_incoming")

    def _search_qty_outgoing(self, operator, value):
        return self._search_product_quantity(operator, value, "qty_outgoing")

    def _search_qty_free(self, operator, value):
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
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id("stock.action_orderpoint")
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
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
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
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
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
        self.ensure_one()
        sequence = self.lot_sequence_id
        return sequence.preview_next() if sequence else False

    def action_view_product_lot(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
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
        return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.stock_forecasted_product_product_action"
        )

    @api.model
    def _normalize_quantities_to_date(self, to_date):
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
        if not self.env.context.get("with_expiration"):
            return None
        max_date = (
            to_date
            if to_date and self.env.context.get("fresh_qty_forecast")
            else self.env.context["with_expiration"]
        )
        return domain_quant & Domain([("removal_date", "<=", max_date)])

    def _read_quantities(self, scope):
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
        self.ensure_one()
        return self

    def _get_description(self, picking_type_id):
        self.ensure_one()
        if picking_type_id.code == "outgoing":
            return self.display_name
        return (
            html2plaintext(self.description)
            if not is_html_empty(self.description)
            else self.display_name
        )

    def _get_picking_description(self, picking_type_id):
        self.ensure_one()
        return {
            "incoming": self.description_pickingin,
            "outgoing": self.description_pickingout,
            "internal": self.description_picking,
        }.get(picking_type_id.code, "")

    def _get_total_routes(self):
        return self.env["stock.route"]

    def _resolve_context_record_ids(self, model, values) -> set[int]:
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
