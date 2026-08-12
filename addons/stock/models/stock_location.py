import calendar
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.api import MODULE_UNINSTALL_FLAG
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.numbers import float_compare

# A cyclic inventory frequency is a number of days added to a date. Anything past
# this is not a schedule, it is a typo or a bad import, and it makes
# ``_compute_next_inventory_date`` overflow — see ``_inventory_freq_bounded``.
MAX_CYCLIC_INVENTORY_DAYS = 36500

# The usages that physically hold countable stock. The virtual counterparts
# (supplier, customer, inventory, production, view) carry quants as bookkeeping,
# so emptiness and inventory scheduling are not meaningful for them.
STOCKED_USAGES = ("internal", "transit")


class StockLocation(models.Model):
    _name = "stock.location"
    _inherit = ["mail.thread", "mail.activity.mixin"]
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
        recursive=True,
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

    # `company_id` is nullable by design ("shared between companies"), and a plain
    # UNIQUE(barcode, company_id) leaves those rows unbound, because PostgreSQL
    # treats NULLs as distinct — two shared locations could carry one barcode,
    # which `_rec_names_search` and barcode scanning then resolve arbitrarily.
    # COALESCE folds "shared" into a single namespace; the partial WHERE keeps
    # NULL *barcodes* distinct, since no barcode is not a barcode to collide on.
    # (`UNIQUE NULLS NOT DISTINCT` cannot express this: it applies to every column
    # of the index, so it would let only one location have no barcode at all.)
    # Named apart from the `_barcode_company_uniq` CONSTRAINT it replaces: a
    # UNIQUE constraint owns its backing index, so an index cannot take that name
    # over. The pre-migration drops the old one.
    _barcode_company_unique_idx = models.UniqueIndex(
        "(barcode, COALESCE(company_id, 0)) WHERE barcode IS NOT NULL",
        "The barcode for a location must be unique per company!",
    )
    _inventory_freq_bounded = models.Constraint(
        f"check(cyclic_inventory_frequency between 0 and {MAX_CYCLIC_INVENTORY_DAYS})",
        "The inventory frequency (days) for a location must be between 0 and 36500.",
    )
    _parent_path_id_idx = models.Index("(parent_path, id)")

    @api.constrains("replenish_location", "location_id", "usage")
    def _check_replenish_location(self):
        if not any(self.mapped("replenish_location")):
            return
        # No sudo needed: `_validate_fields` already hands a constraint its
        # records sudo-ed unless it opts out with `_constrains_sudo`, so this
        # search sees every conflicting location whatever the writer may read.
        # Archived ones are included deliberately — unarchiving one later would
        # silently reintroduce the overlap this exists to prevent.
        replenish_locations = self.with_context(active_test=False).search(
            [("replenish_location", "=", True)]
        )
        for loc in self:
            if not loc.replenish_location or not loc.parent_path:
                continue
            for other in replenish_locations:
                if other.id == loc.id or not other.parent_path:
                    continue
                if loc.parent_path.startswith(
                    other.parent_path
                ) or other.parent_path.startswith(loc.parent_path):
                    raise ValidationError(
                        _(
                            "Another parent/sub replenish location %s exists, if you wish to change it, uncheck it first",
                            other.name,
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_cyclic_inventory_frequency(
                vals.get("cyclic_inventory_frequency")
            )
        res = super().create(vals_list)
        if any("child_ids" in vals for vals in vals_list):
            res._recompute_descendants_warehouse()
        return res

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
        if "location_id" in vals:
            self._recompute_descendants_warehouse()
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
        # The guard is a business rule, so it must not run while a module is being
        # uninstalled — an uninstall cannot satisfy it, and the ORM already skips
        # `@api.ondelete(at_uninstall=False)` handlers for the same reason. This
        # override cannot *be* one of those handlers: it needs `subtree` to widen
        # the deletion, which an ondelete hook cannot do.
        if (
            descendants
            and not self.env.context.get("stock_unlink_subtree")
            and not self.env.context.get(MODULE_UNINSTALL_FLAG)
        ):
            raise UserError(
                _(
                    "You cannot delete location %(location)s: it still contains "
                    "%(count)s sub-location(s) (archived ones included). Delete or "
                    "move them first.",
                    location=self[:1].display_name,
                    count=len(descendants),
                ),
            )
        return super(StockLocation, subtree).unlink()

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
            parent_location = self.env["stock.location"].search(
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
        # `complete_name` already *is* the parent-prefixed path (see
        # `_compute_complete_name`), so the plain name is a read of that stored
        # field, not a second assembly of it. Only the formatted variant, which
        # marks up the two halves, has to look at the parent separately.
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
            # No overflow guard here: `_inventory_freq_bounded` keeps the frequency
            # inside a range that cannot overflow a date, so a bad value is refused
            # at write time instead of turning every later read — and every module
            # upgrade that recomputes this field — into a UserError.
            frequency = timedelta(days=location.cyclic_inventory_frequency)
            if not location.last_inventory_date:
                location.next_inventory_date = today + frequency
            elif location.last_inventory_date + frequency <= today:
                # The planned date has already passed; recount from tomorrow.
                location.next_inventory_date = today + timedelta(days=1)
            else:
                location.next_inventory_date = location.last_inventory_date + frequency

    @api.depends("warehouse_view_ids", "location_id")
    def _compute_warehouse_id(self):
        warehouses = self.env["stock.warehouse"].search(
            [("view_location_id", "parent_of", self.ids)]
        )
        # Deepest view location first, so a location nested in several warehouses
        # resolves to the innermost one. Only ancestors of a given location can
        # match, and a location's ancestors are prefix-ordered, so ordering the
        # whole set by parent_path string is enough to put the deepest match first.
        warehouses = warehouses.sorted(
            lambda w: w.view_location_id.parent_path, reverse=True
        )
        warehouse_id_by_view_location = {
            wh.view_location_id.id: wh.id for wh in warehouses
        }
        # Resolve first, assign once. Assigning False up front and correcting per
        # record afterwards makes this a *write* of NULL followed by a write of the
        # real value whenever the compute is invoked outside the recompute queue
        # (`_recompute_descendants_warehouse` does exactly that).
        for loc in self:
            warehouse_id = False
            if loc.parent_path:
                ancestor_ids = {
                    int(loc_id) for loc_id in loc.parent_path.split("/")[:-1]
                }
                warehouse_id = next(
                    (
                        wh_id
                        for view_id, wh_id in warehouse_id_by_view_location.items()
                        if view_id in ancestor_ids
                    ),
                    False,
                )
            loc.warehouse_id = warehouse_id

    @api.depends("child_ids.usage", "child_ids.child_internal_location_ids")
    def _compute_child_internal_location_ids(self):
        for loc in self:
            loc.child_internal_location_ids = self.search(
                [("id", "child_of", loc.id), ("usage", "=", "internal")]
            )

    @api.depends("usage")
    def _compute_replenish_location(self):
        for loc in self:
            if loc.usage != "internal":
                loc.replenish_location = False

    def _search_is_empty(self, operator, value):
        # Only the positive operator is implemented; the ORM derives the negative
        # (is_empty = False) by negating this domain — `_optimize_boolean_in`
        # rewrites `in [False]` to `not in [True]` and the search-method optimizer
        # inverts what we return here.
        if operator != "in":
            return NotImplemented
        return [("id", "not in", list(self._get_occupied_location_ids()))]

    @api.model
    def _get_occupancy_domain(self):
        """The one definition of "this location is not empty", as a domain over
        ``stock.quant``.

        A quant occupies its location when it carries any stock at all — negative
        included, since negative stock is a discrepancy to resolve, not an absence
        — or when it holds a reservation. ``is_empty``, its search and the archive
        guard all read this, so they cannot drift apart: a location the UI shows
        as empty is exactly one that archives without complaint.

        Summing instead would be wrong twice over: it nets a shortage of one
        product against stock of another, and it reports a purely reserved
        location as empty.
        """
        return Domain("quantity", "!=", 0) | Domain("reserved_quantity", "!=", 0)

    @api.model
    def _get_occupied_location_ids(self, locations=None):
        """Ids of the stock-holding locations that are not empty, restricted to
        ``locations`` when given. One aggregate, never one query per location."""
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

    def _child_of(self, other_location):
        self.ensure_one()
        # A record with no parent_path (unstored) is a child of nothing; a missing
        # other_location (e.g. a ref resolved with raise_if_not_found=False) is an
        # ancestor of nothing.
        if not self.parent_path or not other_location.parent_path:
            return False
        return self.parent_path.startswith(other_location.parent_path)

    def _prefixed_by_parent(self):
        """Whether ``complete_name``/``display_name`` prepend the parent's path.
        True only for a non-view location with a parent: a view aggregates its
        children and isn't shown nested under its own parent."""
        self.ensure_one()
        return bool(self.location_id) and self.usage != "view"

    def _propagate_active(self, active):
        """Cascade (de)activation to the whole subtree, guarding a deactivation
        against locations that back a warehouse or still hold stock."""
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
            # Same definition of "not empty" that `is_empty` reports, so a
            # location the list shows as empty is one that archives.
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
        super(StockLocation, descendant_locations - self).with_context(
            do_not_check_quant=True
        ).write(
            {
                "active": active,
            },
        )

    def _recompute_descendants_warehouse(self):
        """Recompute ``warehouse_id`` for ``self`` and every descendant.

        ``warehouse_id`` is derived from ``parent_path`` (see
        ``_compute_warehouse_id``), which ``@api.depends`` cannot track, so any
        operation that reshapes the tree (create-with-children, reparent) must
        trigger the recompute for the whole subtree explicitly.
        """
        self.with_context(active_test=False).search(
            [("id", "child_of", self.ids)]
        )._compute_warehouse_id()

    def _get_putaway_strategy(
        self, product, quantity=0, package=None, packaging=None, additional_qty=None
    ):
        """Returns the location suggested by the first matching putaway rule.
        Falls back to the first candidate location if self is a view location,
        otherwise returns self. Quantity is expected in the product's default
        UOM and is only used when no package is specified.

        Single-record by contract: the answer is *one* destination, chosen from
        this location's own rules and its own subtree.
        """
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
        category_ancestors = leaf_category
        category = leaf_category
        while category.parent_id:
            category = category.parent_id
            category_ancestors |= category

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
        # The `locations` context is a *cache* of `child_internal_location_ids`,
        # filled once per move group by `stock.move.line._apply_putaway_strategy`.
        # A group can span several destinations, so the cached set is their union
        # and must be narrowed back to this destination's subtree — otherwise the
        # fallback below hands out a candidate belonging to another destination,
        # and every line in the group agrees on it, which defeats the
        # "don't split a package across locations" reset in the caller.
        # `is None` and not falsiness: an explicitly empty candidate set means
        # "nothing available here", not "no cache supplied".
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

    def _get_putaway_qty_by_location(
        self, product, package, package_type, locations, additional_qty=None
    ):
        """Current + planned quantity per candidate location, used to enforce
        storage-category capacity when ranking putaway rules. Counts distinct
        packages when a package is given, otherwise the product quantity (in the
        product's default UoM), summing on-hand quants and inbound move lines.
        Move lines in context ``exclude_sml_ids`` are skipped so a line being
        (re)assigned doesn't count against itself.
        """
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
        """Distinct packages of ``package_type`` already at / inbound to each
        candidate location (on-hand quants + planned move lines)."""
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
        """On-hand + inbound quantity of ``product`` (in its default UoM) at each
        candidate location (on-hand quants + planned move lines, UoM-converted)."""
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

    def _get_next_inventory_date(self):
        """Returns the next inventory date for a quant in this location: the
        earlier of the location's cyclic inventory date and the company's
        annual inventory date, whichever is set, or False if neither is."""
        self.ensure_one()
        if self.usage not in ("internal", "transit"):
            return False
        cyclic_date = self.next_inventory_date
        annual_date = self._get_company_annual_inventory_date()
        if cyclic_date and annual_date:
            return min(cyclic_date, annual_date)
        return cyclic_date or annual_date

    def _get_company_annual_inventory_date(self):
        """The company's next annual inventory date — this year's if still
        upcoming, otherwise next year's — or False when the company configures no
        annual inventory month. The configured day is clamped into each month's
        valid range (handling 0/negative values and leap-year February)."""
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

    def _get_weight(self, exclude_sml_ids=False):
        """Return ``{location: {"net_weight": ..., "forecast_weight": ...}}``.

        :param exclude_sml_ids: set of ``stock.move.line`` ids to leave out of the
            forecast (e.g. the line currently being (re)assigned); named to match
            the ``exclude_sml_ids`` context key callers read it from.
        """
        if not exclude_sml_ids:
            exclude_sml_ids = set()
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

    def _filter_putaway_access(self):
        return self

    def _can_be_used(
        self,
        product,
        quantity=0,
        package=None,
        location_qty=0,
        forecast_weight=None,
        foreign_inbound_ids=None,
    ):
        """Check if product/package can be stored in the location. Quantity
        should be in the product's default UoM; only used when no package is
        specified.

        ``forecast_weight`` and ``foreign_inbound_ids`` are the two per-location
        aggregates this check needs. Both may be supplied by a caller sweeping
        many candidate locations, so the aggregate runs once for the set instead
        of once per location; when either is None it is computed for this
        location alone.
        """
        self.ensure_one()
        if not self.storage_category_id:
            return True
        if not self._can_store_new_product(product, package, foreign_inbound_ids):
            return False
        if forecast_weight is None:
            forecast_weight = self._get_weight(
                self.env.context.get("exclude_sml_ids", set()),
            )[self]["forecast_weight"]
        if package and package.package_type_id:
            return self._can_store_package(package, location_qty, forecast_weight)
        return self._can_store_product(product, quantity, location_qty, forecast_weight)

    def _can_store_new_product(self, product, package, foreign_inbound_ids=None):
        """Whether the storage category's ``allow_new_product`` rule permits
        storing this product/package here (True = allowed).

        ``foreign_inbound_ids`` is the precomputed answer to "which locations
        already expect a *different* product", from
        ``_get_foreign_inbound_location_ids``; None means look it up for this
        location alone.
        """
        self.ensure_one()
        policy = self.storage_category_id.allow_new_product
        if policy not in ("empty", "same"):
            return True
        positive_quant = self.quant_ids.filtered(
            lambda q: q.product_id.uom_id.compare(q.quantity, 0) > 0,
        )
        if policy == "empty":
            return not positive_quant
        # policy == "same": the location may hold a single product only. For a
        # package, `product` isn't set, so fall back to the context products;
        # default to an empty recordset so a caller that sets neither still gets a
        # policy answer instead of a TypeError below.
        product = (
            product or self.env.context.get("products") or self.env["product.product"]
        )
        if (positive_quant and positive_quant.product_id != product) or len(
            product
        ) > 1:
            return False
        if foreign_inbound_ids is None:
            foreign_inbound_ids = self._get_foreign_inbound_location_ids(self, product)
        return self.id not in foreign_inbound_ids

    @api.model
    def _get_foreign_inbound_location_ids(self, locations, product):
        """Ids among ``locations`` that already expect an incoming product other
        than ``product`` — the locations an ``allow_new_product == "same"``
        category must refuse. One aggregate for the whole candidate set."""
        return {
            location.id
            for (location,) in self.env["stock.move.line"]._read_group(
                [
                    ("product_id", "!=", product.id),
                    ("state", "not in", ("done", "cancel")),
                    ("location_dest_id", "in", locations.ids),
                ],
                ["location_dest_id"],
            )
        }

    def _has_weight_capacity(self, added_weight, forecast_weight):
        """Whether the storage category's max weight allows ``added_weight`` on
        top of ``forecast_weight``. A max weight of 0 means no weight limit.
        Rounding-aware: aggregated float weights carry accumulation noise."""
        self.ensure_one()
        max_weight = self.storage_category_id.max_weight
        if not max_weight:
            return True
        weight_precision = self.env["decimal.precision"].precision_get("Stock Weight")
        return (
            float_compare(
                forecast_weight + added_weight,
                max_weight,
                precision_digits=weight_precision,
            )
            <= 0
        )

    def _can_store_package(self, package, location_qty, forecast_weight):
        """Enforce the storage category's max weight and per-package-type
        capacity for a package move into this location (True = fits)."""
        self.ensure_one()
        storage_category = self.storage_category_id
        package_smls = self.env["stock.move.line"].search(
            [
                ("result_package_id", "=", package.id),
                ("state", "not in", ["done", "cancel"]),
            ],
        )
        package_weight = sum(
            package_smls.mapped(
                lambda sml: sml.quantity_product_uom * sml.product_id.weight,
            ),
        )
        if not self._has_weight_capacity(package_weight, forecast_weight):
            return False
        package_capacity = storage_category.package_capacity_ids.filtered(
            lambda pc: pc.package_type_id == package.package_type_id
        )
        if not package_capacity:
            return True
        qty_precision = self.env["decimal.precision"].precision_get("Product Unit")
        return (
            float_compare(
                location_qty,
                package_capacity.quantity,
                precision_digits=qty_precision,
            )
            < 0
        )

    def _can_store_product(self, product, quantity, location_qty, forecast_weight):
        """Enforce the storage category's max weight and per-product capacity for
        a bare-product move into this location (True = fits)."""
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

    def _check_company_not_changed(self, company_id):
        """A location's company is immutable once set; archive and recreate
        instead of moving it between companies."""
        if any(location.company_id.id != company_id for location in self):
            raise UserError(
                _(
                    "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                ),
            )

    @api.model
    def _check_cyclic_inventory_frequency(self, frequency):
        """Refuse an out-of-range cyclic frequency at write time.

        ``_inventory_freq_bounded`` states the same rule in SQL, but a stored
        computed field is recomputed during the flush that precedes the INSERT /
        UPDATE, so ``_compute_next_inventory_date`` would reach the value first
        and raise a bare ``OverflowError`` before PostgreSQL ever saw it. This
        guard runs before the value reaches the cache; the constraint stays as the
        backstop for whatever does not come through the ORM.
        """
        if frequency is None or 0 <= frequency <= MAX_CYCLIC_INVENTORY_DAYS:
            return
        raise ValidationError(
            _(
                "The inventory frequency must be between 0 and %(maximum)s days.",
                maximum=MAX_CYCLIC_INVENTORY_DAYS,
            ),
        )

    def _check_usage_convertible(self, usage):
        """Block a usage change that would strand stock: a location can't become
        a view while it holds products, nor change type while it holds stock.

        Both checks read only the records whose usage actually changes. That is
        equivalent to reading the whole recordset — a record that is not
        converting is already a view, and ``stock.quant`` forbids a quant in a
        view location — but it states the intent plainly.
        """
        modified_locations = self.filtered(lambda l: l.usage != usage)
        if usage == "view" and self.env["stock.quant"].search_count(
            [("location_id", "in", modified_locations.ids)],
            limit=1,
        ):
            raise UserError(
                _(
                    "This location's usage cannot be changed to view as it contains products."
                ),
            )
        if self.env["stock.quant"].search_count(
            [
                ("location_id", "in", modified_locations.ids),
                ("quantity", ">", 0),
            ],
            limit=1,
        ):
            raise UserError(_("Internal locations having stock can't be converted"))

    def _is_outgoing(self):
        self.ensure_one()
        if self.usage == "customer":
            return True
        inter_comp_location = self.env.ref(
            "stock.stock_location_inter_company", raise_if_not_found=False
        )
        return self._child_of(inter_comp_location)

    def should_bypass_reservation(self):
        self.ensure_one()
        return self.usage in ("supplier", "customer", "inventory", "production")
