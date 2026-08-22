import calendar
import logging
from collections import defaultdict
from datetime import timedelta
from typing import NamedTuple

from odoo import _, api, fields, models
from odoo.api import MODULE_UNINSTALL_FLAG
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.numbers import float_compare

from odoo.addons.stock.tools.quantity import resolve_context_record_ids

_logger = logging.getLogger(__name__)

MAX_CYCLIC_INVENTORY_DAYS = 36500

STOCKED_USAGES = ("internal", "transit")

TREE_FIELDS = frozenset({"active", "location_id", "usage"})


class PutawayCapacity(NamedTuple):
    forecast_weight: dict
    foreign_inbound_ids: frozenset
    package_weight: float


class StockLocation(models.Model):
    _name = "stock.location"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
    _description = "Inventory Locations"
    _parent_name = "location_id"
    _parent_store = True
    _order = "complete_name, id"
    _rec_names_search = ["complete_name", "barcode"]
    _check_company_auto = True


    name = fields.Char(string="Location Name", required=True)
    complete_name = fields.Char(
        string="Full Location Name",
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="By unchecking the active field, you may hide a location without deleting it.",
    )
    usage = fields.Selection(
        selection=[
            ("supplier", "Vendor"),
            ("view", "Virtual"),
            ("internal", "Internal"),
            ("customer", "Customer"),
            ("inventory", "Inventory Loss"),
            ("production", "Production"),
            ("transit", "Transit"),
        ],
        string="Location Type",
        required=True,
        default="internal",
        index=True,
        help="* Vendor: Virtual location representing the source location for products coming from your vendors"
        "\n* Virtual: Virtual location used to create a hierarchical structure for your warehouse by aggregating its child locations. Can't directly contain products"
        "\n* Internal: Physical locations inside your warehouses,"
        "\n* Customer: Virtual location representing the destination location for products sent to your customers"
        "\n* Inventory Loss: Virtual location serving as the counterpart for inventory operations done to correct stock levels (Physical inventories)"
        "\n* Production: Virtual counterpart location for production operations. I.e. This location consumes components and produces finished products"
        "\n* Transit: Counterpart location that should be used for inter-company or inter-warehouses operations",
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Parent Location",
        check_company=True,
        index=True,
        help="The parent location that includes this location. Example : The 'Dispatch Zone' is the 'Gate 1' parent location.",
    )
    child_ids = fields.One2many(
        comodel_name="stock.location",
        inverse_name="location_id",
        string="Contains",
    )
    child_internal_location_ids = fields.Many2many(
        comodel_name="stock.location",
        string="Internal locations among descendants",
        compute="_compute_child_internal_location_ids",
        help="This location (if it's internal) and all its descendants filtered by type=Internal.",
    )
    parent_path = fields.Char(index=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
        help="Let this field empty if this location is shared between companies",
    )
    replenish_location = fields.Boolean(
        string="Replenishments",
        compute="_compute_replenish_location",
        store=True,
        readonly=False,
        copy=False,
        help="Trigger replenishment suggestions for this location when required",
    )
    removal_strategy_id = fields.Many2one(
        comodel_name="product.removal",
        string="Removal Strategy",
        help="Defines the default method used for suggesting the exact location (shelf) "
        "where to take the products from, which lot etc. for this location. "
        "This method can be enforced at the product category level, "
        "and a fallback is made on the parent locations if none is set here.\n\n"
        "FIFO: products/lots that were stocked first will be moved out first.\n"
        "LIFO: products/lots that were stocked last will be moved out first.\n"
        "Closest Location: products/lots closest to the target location will be moved out first.\n"
        "Least Packages: products/lots that were stocked in package with least amount of qty will be moved out first.\n"
        "FEFO: products/lots with the closest removal date will be moved out first "
        '(the availability of this method depends on the "Expiration Dates" setting).',
    )
    putaway_rule_ids = fields.One2many(
        comodel_name="stock.putaway.rule",
        inverse_name="location_in_id",
        string="Putaway Rules",
    )
    barcode = fields.Char(string="Barcode", copy=False)
    quant_ids = fields.One2many(
        comodel_name="stock.quant",
        inverse_name="location_id",
    )
    cyclic_inventory_frequency = fields.Integer(
        string="Inventory Frequency",
        default=0,
        help=" When different than 0, inventory count date for products stored at this location will be automatically set at the defined frequency.",
    )
    last_inventory_date = fields.Date(
        string="Last Inventory",
        readonly=True,
        help="Date of the last inventory at this location.",
    )
    next_inventory_date = fields.Date(
        string="Next Expected",
        compute="_compute_next_inventory_date",
        store=True,
        help="Date for next planned inventory based on cyclic schedule.",
    )
    warehouse_view_ids = fields.One2many(
        comodel_name="stock.warehouse",
        inverse_name="view_location_id",
        readonly=True,
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        compute="_compute_warehouse_id",
        store=True,
        recursive=True,
    )
    storage_category_id = fields.Many2one(
        comodel_name="stock.storage.category",
        string="Storage Category",
        check_company=True,
        index="btree_not_null",
    )
    outgoing_move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="location_id",
    )
    incoming_move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="location_dest_id",
    )
    net_weight = fields.Float(
        string="Net Weight",
        compute="_compute_weight",
    )
    forecast_weight = fields.Float(
        string="Forecasted Weight",
        compute="_compute_weight",
    )
    is_empty = fields.Boolean(
        string="Is Empty",
        compute="_compute_is_empty",
        search="_search_is_empty",
    )


    _barcode_company_unique_idx = models.UniqueIndex(
        "(barcode, COALESCE(company_id, 0)) WHERE barcode IS NOT NULL",
        "The barcode for a location must be unique per company!",
    )
    _parent_path_id_idx = models.Index("(parent_path, id)")


    _inventory_freq_bounded = models.Constraint(
        f"check(cyclic_inventory_frequency between 0 and {MAX_CYCLIC_INVENTORY_DAYS})",
        "The inventory frequency (days) for a location must be between 0 and "
        f"{MAX_CYCLIC_INVENTORY_DAYS}.",
    )


    @api.constrains("replenish_location", "location_id", "usage")
    def _check_replenish_location(self):
        replenish_locations = self.filtered("replenish_location")
        if not replenish_locations:
            return
        others = self.with_context(active_test=False).search(
            [("replenish_location", "=", True)],
        )
        for location in replenish_locations:
            if not location.parent_path:
                continue
            for other in others:
                if other == location or not other.parent_path:
                    continue
                if location.parent_path.startswith(
                    other.parent_path
                ) or other.parent_path.startswith(location.parent_path):
                    raise ValidationError(
                        _(
                            "Another parent/sub replenish location %s exists, if you wish to change it, uncheck it first",
                            other.display_name,
                        ),
                    )

    @api.constrains("usage")
    def _check_inventory_loss_location(self):
        inventory_locations = self.filtered(lambda l: l.usage == "inventory")
        if not inventory_locations:
            return
        if self.env["stock.picking.type"].search_count(
            [
                ("code", "=", "mrp_operation"),
                ("default_location_dest_id", "in", inventory_locations.ids),
            ],
            limit=1,
        ):
            raise ValidationError(
                _(
                    "You cannot set a location's type to Inventory Loss while it is the destination location of a manufacturing operation type."
                ),
            )

    def _check_company_not_changed(self, company_id):
        if any(location.company_id.id != company_id for location in self):
            raise UserError(
                _(
                    "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                ),
            )

    @api.model
    def _check_cyclic_inventory_frequency(self, frequency):
        if frequency is None or 0 <= frequency <= MAX_CYCLIC_INVENTORY_DAYS:
            return
        raise ValidationError(
            _(
                "The inventory frequency must be between 0 and %(maximum)s days.",
                maximum=MAX_CYCLIC_INVENTORY_DAYS,
            ),
        )

    def _check_usage_convertible(self, usage):
        modified_locations = self.filtered(lambda location: location.usage != usage)
        if not modified_locations:
            return
        Quant = self.env["stock.quant"]
        if usage == "view":
            blocking = Quant.search(
                [("location_id", "in", modified_locations.ids)],
                limit=1,
            ).location_id
            if blocking:
                raise UserError(
                    _(
                        "A view location groups its children and cannot hold "
                        "products; %s still does.",
                        blocking.display_name,
                    ),
                )
        blocking = Quant.search(
            [
                ("location_id", "in", modified_locations.ids),
                ("quantity", ">", 0),
            ],
            limit=1,
        ).location_id
        if blocking:
            raise UserError(
                _(
                    "%s still holds stock, so its type cannot be changed.",
                    blocking.display_name,
                ),
            )


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_cyclic_inventory_frequency(
                vals.get("cyclic_inventory_frequency")
            )
        locations = super().create(vals_list)
        locations._invalidate_location_tree()
        return locations

    def write(self, vals):
        if "cyclic_inventory_frequency" in vals:
            self._check_cyclic_inventory_frequency(vals["cyclic_inventory_frequency"])
        if "company_id" in vals:
            self._check_company_not_changed(vals["company_id"])
        if "usage" in vals:
            self._check_usage_convertible(vals["usage"])
        if "active" in vals:
            self._propagate_active(vals["active"])

        res = super().write(vals)
        if not TREE_FIELDS.isdisjoint(vals):
            self._invalidate_location_tree()
        return res

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for location, vals in zip(self, vals_list, strict=True):
                vals["name"] = _("%s (copy)", location.name)
        return vals_list

    def unlink(self):
        subtree = self.with_context(active_test=False).search(
            [("id", "child_of", self.ids)],
        )
        descendants = subtree - self
        if (
            descendants
            and not self.env.context.get("stock_unlink_subtree")
            and not self.env.context.get(MODULE_UNINSTALL_FLAG)
        ):
            blocking = self.browse(
                location.id
                for location in self
                if any(child._child_of(location) for child in descendants)
            )
            raise UserError(
                _(
                    "You cannot delete location %(location)s: it still contains "
                    "%(count)s sub-location(s) (archived ones included). Delete or "
                    "move them first.",
                    location=blocking[:1].display_name,
                    count=len(
                        descendants.filtered(
                            lambda child, parent=blocking[:1]: child._child_of(parent)
                        )
                    ),
                ),
            )
        res = super(StockLocation, subtree).unlink()
        self._invalidate_location_tree()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_master_data(self):
        inter_company_location = self.env.ref("stock.stock_location_inter_company")
        if inter_company_location in self:
            raise ValidationError(
                _(
                    "The %s location is required by the Inventory app and cannot be deleted, but you can archive it.",
                    inter_company_location.name,
                ),
            )

    @api.model
    def name_create(self, name):
        if name:
            name_split = name.split("/")
            parent_location = self.search(
                [
                    ("complete_name", "=", "/".join(name_split[:-1])),
                    ("company_id", "in", [False, self.env.company.id]),
                ],
                limit=1,
            )
            new_location = self.create(
                {
                    "name": name_split[-1],
                    "location_id": parent_location.id if parent_location else False,
                },
            )
            return new_location.id, new_location.display_name
        return super().name_create(name)


    @api.depends("complete_name", "name", "location_id.complete_name", "usage")
    @api.depends_context("formatted_display_name")
    def _compute_display_name(self):
        formatted = self.env.context.get("formatted_display_name")
        for location in self:
            if formatted and location._prefixed_by_parent():
                location.display_name = (
                    f"--{location.location_id.complete_name}/--{location.name}"
                )
            else:
                location.display_name = location.complete_name

    @api.depends(
        "outgoing_move_line_ids.quantity_product_uom",
        "incoming_move_line_ids.quantity_product_uom",
        "outgoing_move_line_ids.state",
        "incoming_move_line_ids.state",
        "outgoing_move_line_ids.product_id.weight",
        "incoming_move_line_ids.product_id.weight",
        "quant_ids.quantity",
        "quant_ids.product_id.weight",
    )
    def _compute_weight(self):
        weight_by_location = self._get_weight()
        for location in self:
            location.net_weight = weight_by_location[location]["net_weight"]
            location.forecast_weight = weight_by_location[location]["forecast_weight"]

    @api.depends("name", "location_id.complete_name", "usage")
    def _compute_complete_name(self):
        for location in self:
            if location._prefixed_by_parent():
                location.complete_name = (
                    f"{location.location_id.complete_name}/{location.name}"
                )
            else:
                location.complete_name = location.name

    def _compute_is_empty(self):
        occupied_ids = self._get_occupied_location_ids(self)
        for location in self:
            location.is_empty = location.id not in occupied_ids

    @api.depends(
        "cyclic_inventory_frequency", "last_inventory_date", "usage", "company_id"
    )
    def _compute_next_inventory_date(self):
        today = fields.Date.today()
        for location in self:
            if not (
                location.company_id
                and location.usage in STOCKED_USAGES
                and location.cyclic_inventory_frequency > 0
            ):
                location.next_inventory_date = False
                continue
            frequency = timedelta(days=location.cyclic_inventory_frequency)
            if not location.last_inventory_date:
                location.next_inventory_date = today + frequency
            elif location.last_inventory_date + frequency <= today:
                location.next_inventory_date = today + timedelta(days=1)
            else:
                location.next_inventory_date = location.last_inventory_date + frequency

    @api.depends(
        "warehouse_view_ids", "warehouse_view_ids.active", "location_id.warehouse_id"
    )
    def _compute_warehouse_id(self):
        for location in self:
            location.warehouse_id = (
                location.warehouse_view_ids[:1] or location.location_id.warehouse_id
            )

    def _compute_child_internal_location_ids(self):
        internal_locations = self.search_fetch(
            [("id", "child_of", self.ids), ("usage", "=", "internal")],
            ["parent_path"],
        )
        descendant_ids = defaultdict(list)
        for location in internal_locations:
            for ancestor_id in map(int, location.parent_path.split("/")[:-1]):
                descendant_ids[ancestor_id].append(location.id)
        for location in self:
            location.child_internal_location_ids = self.browse(
                descendant_ids.get(location.id, ()),
            )

    @api.depends("usage")
    def _compute_replenish_location(self):
        for loc in self:
            if loc.usage != "internal":
                loc.replenish_location = False


    def _search_is_empty(self, operator, value):
        if operator != "in" or set(value) != {True}:
            return NotImplemented
        return [("id", "not in", list(self._get_occupied_location_ids()))]


    @api.model
    def _get_occupancy_domain(self):
        return Domain("quantity", "!=", 0) | Domain("reserved_quantity", "!=", 0)

    def _get_occupied_location_ids(self, locations=None):
        domain = self._get_occupancy_domain() & Domain(
            "location_id.usage", "in", STOCKED_USAGES
        )
        if locations is not None:
            domain &= Domain("location_id", "in", locations.ids)
        return {
            location.id
            for (location,) in self.env["stock.quant"]._read_group(
                domain, ["location_id"]
            )
        }

    @api.model
    def _get_allocation_source_ids(self, view_location_ids):
        return self.search(
            [
                ("id", "child_of", view_location_ids),
                ("usage", "!=", "supplier"),
            ],
        ).ids


    def _child_of(self, other_location):
        self.ensure_one()
        if not self.parent_path or not other_location.parent_path:
            return False
        return self.parent_path.startswith(other_location.parent_path)

    def _prefixed_by_parent(self):
        self.ensure_one()
        return bool(self.location_id) and self.usage != "view"

    def _is_outgoing(self):
        self.ensure_one()
        if self.usage == "customer":
            return True
        inter_company_location = (
            self.env.ref("stock.stock_location_inter_company", raise_if_not_found=False)
            or self.browse()
        )
        return self._child_of(inter_company_location)

    def should_bypass_reservation(self):
        self.ensure_one()
        return self.usage in ("supplier", "customer", "inventory", "production")

    def _propagate_active(self, active):
        self = self.filtered(lambda location: location.active != bool(active))
        if not self:
            return
        if self.env.context.get("do_not_check_quant"):
            return
        descendant_locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("id", "child_of", self.ids)])
        )
        if not active:
            blocking_warehouse = self.env["stock.warehouse"].search(
                [
                    ("active", "=", True),
                    "|",
                    ("lot_stock_id", "in", descendant_locations.ids),
                    ("view_location_id", "in", descendant_locations.ids),
                ],
                limit=1,
            )
            if blocking_warehouse:
                location = (
                    blocking_warehouse.lot_stock_id
                    if blocking_warehouse.lot_stock_id in descendant_locations
                    else blocking_warehouse.view_location_id
                )
                raise UserError(
                    _(
                        "You cannot archive location %(location)s because it is used by warehouse %(warehouse)s",
                        location=location.display_name,
                        warehouse=blocking_warehouse.display_name,
                    ),
                )
            internal_descendants = descendant_locations.filtered(
                lambda l: l.usage == "internal"
            )
            blocking_quants = self.env["stock.quant"].search(
                self._get_occupancy_domain()
                & Domain("location_id", "in", internal_descendants.ids),
            )
            if blocking_quants:
                raise UserError(
                    _(
                        "You can't disable locations %s because they still contain products.",
                        ", ".join(blocking_quants.mapped("location_id.display_name")),
                    ),
                )
        (descendant_locations - self).with_context(do_not_check_quant=True).write(
            {
                "active": active,
            },
        )

    @api.model
    def _invalidate_location_tree(self):
        self.invalidate_model(["child_internal_location_ids"])


    def _filter_putaway_access(self):
        return self

    def _get_putaway_strategy(
        self, product, quantity=0, package=None, packaging=None, additional_qty=None
    ):
        self.ensure_one()
        self = self._filter_putaway_access()
        products = self.env.context.get("products", self.env["product.product"])
        products |= product
        package_type = self.env["stock.package.type"]
        if package:
            package_type = package.package_type_id
        elif packaging:
            package_type = packaging.package_type_id

        leaf_category = (
            products.categ_id
            if len(products.categ_id) == 1
            else self.env["product.category"]
        )
        category_ancestors = leaf_category.browse(
            map(int, (leaf_category.parent_path or "").split("/")[:-1])
        )

        putaway_rules = self.putaway_rule_ids.filtered(
            lambda rule: (
                (not rule.product_id or rule.product_id in products)
                and (not rule.category_id or rule.category_id in category_ancestors)
                and (not rule.package_type_ids or package_type in rule.package_type_ids)
            )
        )

        putaway_rules = putaway_rules.sorted(
            lambda rule: (
                bool(rule.package_type_ids),
                bool(rule.product_id),
                bool(rule.category_id == leaf_category),
                bool(rule.category_id),
            ),
            reverse=True,
        )

        putaway_location = None
        locations = self.env.context.get("locations")
        if locations is None:
            locations = self.child_internal_location_ids
        else:
            locations = locations.filtered(lambda loc: loc._child_of(self))
        if putaway_rules:
            qty_by_location = self._get_putaway_qty_by_location(
                product, package, package_type, locations, additional_qty
            )
            putaway_location = putaway_rules._get_putaway_location(
                product, quantity, package, packaging, qty_by_location
            )

        if not putaway_location:
            putaway_location = (
                locations[0] if locations and self.usage == "view" else self
            )

        return putaway_location

    def _get_putaway_strategy_batch(
        self, product, quantities, package=None, packaging=None, additional_qty=None
    ):
        self.ensure_one()
        qty_by_location = defaultdict(float, additional_qty or {})
        locations = []
        for quantity in quantities:
            location = self._get_putaway_strategy(
                product,
                quantity,
                package=package,
                packaging=packaging,
                additional_qty=qty_by_location,
            )
            qty_by_location[location.id] += quantity
            locations.append(location)
        return locations

    def _get_putaway_qty_by_location(
        self, product, package, package_type, locations, additional_qty=None
    ):
        qty_by_location = defaultdict(int)
        if locations.storage_category_id:
            exclude_sml_ids = list(self.env.context.get("exclude_sml_ids", set()))
            if package and package.package_type_id:
                qty_by_location.update(
                    self._get_putaway_package_count_by_location(
                        package_type, locations, exclude_sml_ids
                    )
                )
            else:
                qty_by_location.update(
                    self._get_putaway_product_qty_by_location(
                        product, locations, exclude_sml_ids
                    )
                )

        if additional_qty:
            for location_id, qty in additional_qty.items():
                qty_by_location[location_id] += qty
        return qty_by_location

    def _get_putaway_package_count_by_location(
        self, package_type, locations, exclude_sml_ids
    ):
        count_by_location = defaultdict(int)
        move_line_data = self.env["stock.move.line"]._read_group(
            [
                ("id", "not in", exclude_sml_ids),
                ("result_package_id.package_type_id", "=", package_type.id),
                ("state", "not in", ["draft", "done", "cancel"]),
                ("location_dest_id", "in", locations.ids),
            ],
            ["location_dest_id"],
            ["result_package_id:count_distinct"],
        )
        for location_dest, count in move_line_data:
            count_by_location[location_dest.id] += count
        quant_data = self.env["stock.quant"]._read_group(
            [
                ("package_id.package_type_id", "=", package_type.id),
                ("location_id", "in", locations.ids),
            ],
            ["location_id"],
            ["package_id:count_distinct"],
        )
        for location, count in quant_data:
            count_by_location[location.id] += count
        return count_by_location

    def _get_putaway_product_qty_by_location(self, product, locations, exclude_sml_ids):
        qty_by_location = defaultdict(float)
        quant_data = self.env["stock.quant"]._read_group(
            [
                ("product_id", "=", product.id),
                ("location_id", "in", locations.ids),
            ],
            ["location_id"],
            ["quantity:sum"],
        )
        for location, quantity_sum in quant_data:
            qty_by_location[location.id] += quantity_sum
        move_line_data = self.env["stock.move.line"]._read_group(
            [
                ("id", "not in", exclude_sml_ids),
                ("product_id", "=", product.id),
                ("location_dest_id", "in", locations.ids),
                ("state", "not in", ["draft", "done", "cancel"]),
            ],
            ["location_dest_id"],
            ["quantity:array_agg", "product_uom_id:array_agg"],
        )
        for location_dest, quantity_list, uom_ids in move_line_data:
            uoms = self.env["uom.uom"].browse(uom_ids)
            current_qty = sum(
                uom._compute_quantity(float(qty), product.uom_id)
                for qty, uom in zip(quantity_list, uoms, strict=True)
            )
            qty_by_location[location_dest.id] += current_qty
        return qty_by_location


    def _get_effective_product(self, product):
        return (
            product or self.env.context.get("products") or self.env["product.product"]
        )

    def _get_putaway_capacity(self, product, package=None):
        if not self:
            return PutawayCapacity({}, frozenset(), 0.0)
        weight_by_location = self._get_weight(
            self.env.context.get("exclude_sml_ids", set()),
        )
        return PutawayCapacity(
            forecast_weight={
                location.id: weights["forecast_weight"]
                for location, weights in weight_by_location.items()
            },
            foreign_inbound_ids=frozenset(
                self._get_foreign_inbound_location_ids(
                    self, self._get_effective_product(product)
                ),
            ),
            package_weight=self._get_package_weight(package),
        )

    @api.model
    def _get_package_weight(self, package):
        if not package:
            return 0.0
        package_smls = self.env["stock.move.line"].search(
            [
                ("result_package_id", "=", package.id),
                ("state", "not in", ["done", "cancel"]),
            ],
        )
        return sum(
            package_smls.mapped(
                lambda sml: sml.quantity_product_uom * sml.product_id.weight,
            ),
        )

    def _get_weight(self, exclude_sml_ids=None):
        exclude_sml_ids = exclude_sml_ids or set()
        Product = self.env["product.product"]
        StockMoveLine = self.env["stock.move.line"]

        quants = self.env["stock.quant"]._read_group(
            [("location_id", "in", self.ids)],
            groupby=["location_id", "product_id"],
            aggregates=["quantity:sum"],
        )
        base_domain = Domain("state", "not in", ["draft", "done", "cancel"]) & Domain(
            "id",
            "not in",
            tuple(exclude_sml_ids),
        )
        outgoing_move_lines = StockMoveLine._read_group(
            Domain("location_id", "in", self.ids) & base_domain,
            groupby=["location_id", "product_id"],
            aggregates=["quantity_product_uom:sum"],
        )
        incoming_move_lines = StockMoveLine._read_group(
            Domain("location_dest_id", "in", self.ids) & base_domain,
            groupby=["location_dest_id", "product_id"],
            aggregates=["quantity_product_uom:sum"],
        )

        products = Product.union(
            *(
                product
                for __, product, __ in quants
                + outgoing_move_lines
                + incoming_move_lines
            ),
        )
        products.fetch(["weight"])

        weight_by_location = defaultdict(lambda: defaultdict(float))
        for loc, product, quantity_sum in quants:
            weight = quantity_sum * product.weight
            weight_by_location[loc]["net_weight"] += weight
            weight_by_location[loc]["forecast_weight"] += weight

        for loc, product, quantity_product_uom_sum in outgoing_move_lines:
            weight_by_location[loc]["forecast_weight"] -= (
                quantity_product_uom_sum * product.weight
            )

        for dest_loc, product, quantity_product_uom_sum in incoming_move_lines:
            weight_by_location[dest_loc]["forecast_weight"] += (
                quantity_product_uom_sum * product.weight
            )

        return weight_by_location

    def _can_be_used(
        self,
        product,
        quantity=0,
        package=None,
        location_qty=0,
        capacity=None,
    ):
        self.ensure_one()
        if not self.storage_category_id:
            return True
        if capacity is None:
            capacity = self._get_putaway_capacity(product, package)
        if not self._can_store_new_product(
            product, package, capacity.foreign_inbound_ids
        ):
            return False
        forecast_weight = capacity.forecast_weight.get(self.id, 0.0)
        if package and package.package_type_id:
            return self._can_store_package(
                package, location_qty, forecast_weight, capacity.package_weight
            )
        return self._can_store_product(product, quantity, location_qty, forecast_weight)

    def _can_store_new_product(self, product, package, foreign_inbound_ids=None):
        self.ensure_one()
        policy = self.storage_category_id.allow_new_product
        if policy not in ("empty", "same"):
            return True
        positive_quant = self.quant_ids.filtered(
            lambda q: q.product_id.uom_id.compare(q.quantity, 0) > 0,
        )
        if policy == "empty":
            return not positive_quant
        product = self._get_effective_product(product)
        if (positive_quant and positive_quant.product_id != product) or len(
            product
        ) > 1:
            return False
        if foreign_inbound_ids is None:
            foreign_inbound_ids = self._get_foreign_inbound_location_ids(self, product)
        return self.id not in foreign_inbound_ids

    @api.model
    def _get_foreign_inbound_location_ids(self, locations, products):
        return {
            location.id
            for (location,) in self.env["stock.move.line"]._read_group(
                [
                    ("product_id", "not in", products.ids),
                    ("state", "not in", ("done", "cancel")),
                    ("location_dest_id", "in", locations.ids),
                ],
                ["location_dest_id"],
            )
        }

    def _has_weight_capacity(self, added_weight, forecast_weight):
        self.ensure_one()
        max_weight = self.storage_category_id.max_weight
        if not max_weight:
            return True
        weight_precision = self.env["decimal.precision"].get_precision("Stock Weight")
        return (
            float_compare(
                forecast_weight + added_weight,
                max_weight,
                precision_digits=weight_precision,
            )
            <= 0
        )

    def _can_store_package(
        self, package, location_qty, forecast_weight, package_weight=None
    ):
        self.ensure_one()
        storage_category = self.storage_category_id
        if package_weight is None:
            package_weight = self._get_package_weight(package)
        if not self._has_weight_capacity(package_weight, forecast_weight):
            return False
        package_capacity = storage_category.package_capacity_ids.filtered(
            lambda pc: pc.package_type_id == package.package_type_id
        )
        if not package_capacity:
            return True
        qty_precision = self.env["decimal.precision"].get_precision("Product Unit")
        return (
            float_compare(
                location_qty,
                package_capacity.quantity,
                precision_digits=qty_precision,
            )
            < 0
        )

    def _can_store_product(self, product, quantity, location_qty, forecast_weight):
        self.ensure_one()
        storage_category = self.storage_category_id
        if not self._has_weight_capacity(product.weight * quantity, forecast_weight):
            return False
        product_capacity = storage_category.product_capacity_ids.filtered(
            lambda pc: pc.product_id == product,
        )
        if not product_capacity:
            return True
        if product.uom_id.compare(location_qty, product_capacity.quantity) >= 0:
            return False
        return (
            product.uom_id.compare(quantity + location_qty, product_capacity.quantity)
            <= 0
        )


    def _get_next_inventory_date(self):
        self.ensure_one()
        if self.usage not in STOCKED_USAGES:
            return False
        cyclic_date = self.next_inventory_date
        annual_date = self._get_company_annual_inventory_date()
        if cyclic_date and annual_date:
            return min(cyclic_date, annual_date)
        return cyclic_date or annual_date

    def _get_company_annual_inventory_date(self):
        self.ensure_one()
        if not self.company_id.annual_inventory_month:
            return False
        today = fields.Date.today()
        month = int(self.company_id.annual_inventory_month)
        day = max(self.company_id.annual_inventory_day, 1)
        day = min(day, calendar.monthrange(today.year, month)[1])
        annual_date = today.replace(month=month, day=day)
        if annual_date <= today:
            day = min(day, calendar.monthrange(today.year + 1, month)[1])
            annual_date = annual_date.replace(day=day, year=today.year + 1)
        return annual_date


    def _quantity_domains_from_context(self) -> tuple[Domain, Domain, Domain]:
        location_ids = self._scope_ids_from_context()
        fell_back = location_ids is None
        if fell_back:
            location_ids = set(
                self.env["stock.warehouse"]
                .search([("company_id", "in", self.env.companies.ids)])
                .mapped("view_location_id")
                .ids
            )
        if _logger.isEnabledFor(logging.DEBUG):
            context = self.env.context
            _logger.debug(
                "quantity scope: locations=%s%s from %s, companies=%s",
                sorted(location_ids) or "NONE (every domain is FALSE)",
                " (fallback: no scope in the context)" if fell_back else "",
                {
                    key: context[key]
                    for key in (
                        "location",
                        "search_location",
                        "warehouse_id",
                        "search_warehouse",
                        "strict",
                        "skip_in_progress",
                    )
                    if key in context
                }
                or "no scope keys",
                self.env.companies.ids,
            )
        return self._quantity_domains(location_ids)

    def _scope_ids_from_context(self) -> set[int] | None:
        context = self.env.context
        location = context.get("location") or context.get("search_location")
        if location and not isinstance(location, list):
            location = [location]
        warehouse = context.get("warehouse_id") or context.get("search_warehouse")
        if warehouse and not isinstance(warehouse, list):
            warehouse = [warehouse]

        if not warehouse:
            if not location:
                return None
            return resolve_context_record_ids(self.env, "stock.location", location)

        view_location_ids = set(
            self.env["stock.warehouse"]
            .browse(
                resolve_context_record_ids(self.env, "stock.warehouse", warehouse),
            )
            .mapped("view_location_id")
            .ids
        )
        if not location:
            return view_location_ids
        parent_paths = [
            path
            for path in self.browse(view_location_ids).mapped("parent_path")
            if path
        ]
        return {
            candidate.id
            for candidate in self.browse(
                resolve_context_record_ids(self.env, "stock.location", location),
            )
            if candidate.parent_path
            and any(candidate.parent_path.startswith(path) for path in parent_paths)
        }

    def _quantity_domains(self, location_ids) -> tuple[Domain, Domain, Domain]:
        if not location_ids:
            return (Domain.FALSE,) * 3
        location_ids = list(location_ids)
        if self.env.context.get("strict"):
            loc_domain = Domain("location_id", "in", location_ids)
            dest_loc_domain = Domain("location_dest_id", "in", location_ids)
            dest_loc_domain_out = Domain("location_dest_id", "not in", location_ids)
            return (
                loc_domain,
                dest_loc_domain & ~loc_domain,
                loc_domain & dest_loc_domain_out,
            )

        loc_domain = Domain("location_id", "child_of", location_ids)
        dest_loc_domain_done = Domain("location_dest_id", "child_of", location_ids)
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
                ("location_final_id", "child_of", location_ids),
                "&",
                ("location_final_id", "=", False),
                ("location_dest_id", "child_of", location_ids),
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
