import calendar
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain


class StockLocation(models.Model):
    _name = "stock.location"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Inventory Locations"
    _parent_name = "location_id"
    _parent_store = True
    _order = "complete_name, id"
    _rec_names_search = ["complete_name", "barcode"]
    _check_company_auto = True

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

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
    )  # used to compute weight
    incoming_move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="location_dest_id",
    )  # used to compute weight
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

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    _barcode_company_uniq = models.Constraint(
        "unique (barcode,company_id)",
        "The barcode for a location must be unique per company!",
    )
    _inventory_freq_nonneg = models.Constraint(
        "check(cyclic_inventory_frequency >= 0)",
        "The inventory frequency (days) for a location must be non-negative",
    )
    _parent_path_id_idx = models.Index("(parent_path, id)")

    @api.constrains("replenish_location", "location_id", "usage")
    def _check_replenish_location(self):
        if not any(self.mapped("replenish_location")):
            return
        # Two replenish locations conflict when one is an ancestor of the other:
        # their subtrees overlap and orderpoints would double-count. Siblings
        # (disjoint subtrees) are fine. Fetch all replenish locations once and
        # compare parent_path, instead of a child_of search per record.
        replenish_locations = self.search([("replenish_location", "=", True)])
        for loc in self:
            if not loc.replenish_location or not loc.parent_path:
                continue
            for other in replenish_locations:
                if other.id == loc.id or not other.parent_path:
                    continue
                # other is an ancestor of loc, or loc is an ancestor of other
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
    def _check_scrap_location(self):
        inventory_locations = self.filtered(lambda l: l.usage == "inventory")
        if not inventory_locations:
            return
        # The domain already constrains the destination to be one of these
        # inventory locations, so a single match is a conflict.
        if self.env["stock.picking.type"].search_count(
            [
                ("code", "=", "mrp_operation"),
                ("default_location_dest_id", "in", inventory_locations.ids),
            ],
            limit=1,
        ):
            raise ValidationError(
                _(
                    "You cannot set a location as a scrap location when it is assigned as a destination location for a manufacturing type operation."
                ),
            )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        # New nodes compute their own warehouse_id via @api.depends. Only a
        # subtree reparented through child_ids needs its descendants recomputed,
        # since warehouse_id follows parent_path which @api.depends can't track.
        if any("child_ids" in vals for vals in vals_list):
            res._recompute_descendants_warehouse()
        return res

    def write(self, vals):
        if "company_id" in vals:
            self._check_company_not_changed(vals["company_id"])
        if "usage" in vals:
            self._check_usage_convertible(vals["usage"])
        if "active" in vals:
            self._propagate_active(vals["active"])

        res = super().write(vals)
        if "location_id" in vals:
            # A subtree move changes warehouse_id for every descendant, but
            # @api.depends only recomputes the directly-written records; the
            # descendants follow parent_path, so recompute the moved subtree.
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
        # active_test=False so archived descendants are unlinked too, instead
        # of being orphaned (location_id set NULL). Matches the traversal in write().
        return super(
            StockLocation,
            self.with_context(active_test=False).search([("id", "child_of", self.ids)]),
        ).unlink()

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
    def default_get(self, fields):
        res = super().default_get(fields)
        if "barcode" in fields and "barcode" not in res and res.get("complete_name"):
            res["barcode"] = res["complete_name"]
        return res

    @api.model
    def name_create(self, name):
        if name:
            name_split = name.split("/")
            parent_location = self.env["stock.location"].search(
                [
                    ("complete_name", "=", "/".join(name_split[:-1])),
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

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("name", "location_id.complete_name", "usage")
    @api.depends_context("formatted_display_name")
    def _compute_display_name(self):
        super()._compute_display_name()
        for location in self:
            if not location._prefixed_by_parent():
                continue
            if location.env.context.get("formatted_display_name"):
                location.display_name = (
                    f"--{location.location_id.complete_name}/--{location.name}"
                )
            else:
                location.display_name = (
                    f"{location.location_id.complete_name}/{location.name}"
                )

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
        qty_by_location = dict(
            self.env["stock.quant"]._read_group(
                [
                    ("location_id.usage", "in", ("internal", "transit")),
                    ("location_id", "in", self.ids),
                ],
                ["location_id"],
                ["quantity:sum"],
            )
        )
        for location in self:
            location.is_empty = qty_by_location.get(location, 0) <= 0

    @api.depends(
        "cyclic_inventory_frequency", "last_inventory_date", "usage", "company_id"
    )
    def _compute_next_inventory_date(self):
        today = fields.Date.today()
        for location in self:
            if not (
                location.company_id
                and location.usage in ("internal", "transit")
                and location.cyclic_inventory_frequency > 0
            ):
                location.next_inventory_date = False
                continue
            try:
                # timedelta() stays inside the try: a very large frequency
                # overflows here, and that must surface as the UserError below.
                frequency = timedelta(days=location.cyclic_inventory_frequency)
                if not location.last_inventory_date:
                    location.next_inventory_date = today + frequency
                elif location.last_inventory_date + frequency <= today:
                    # The planned date has already passed; recount from tomorrow.
                    location.next_inventory_date = today + timedelta(days=1)
                else:
                    location.next_inventory_date = (
                        location.last_inventory_date + frequency
                    )
            except OverflowError:
                raise UserError(
                    _(
                        "The selected Inventory Frequency (Days) creates a date too far into the future."
                    ),
                ) from None

    @api.depends("warehouse_view_ids", "location_id")
    def _compute_warehouse_id(self):
        warehouses = self.env["stock.warehouse"].search(
            [("view_location_id", "parent_of", self.ids)]
        )
        # Deepest view location first, so a location nested in several
        # warehouses resolves to the innermost one.
        warehouses = warehouses.sorted(
            lambda w: w.view_location_id.parent_path, reverse=True
        )
        warehouse_id_by_view_location = {
            wh.view_location_id.id: wh.id for wh in warehouses
        }
        self.warehouse_id = False
        for loc in self:
            if not loc.parent_path:
                continue
            ancestor_ids = {int(loc_id) for loc_id in loc.parent_path.split("/")[:-1]}
            for view_location_id, warehouse_id in warehouse_id_by_view_location.items():
                if view_location_id in ancestor_ids:
                    loc.warehouse_id = warehouse_id
                    break

    @api.depends("child_ids.usage", "child_ids.child_internal_location_ids")
    def _compute_child_internal_location_ids(self):
        # recursive=True makes the ORM invoke this compute one record at a time,
        # so a single grouped search buys nothing here.
        for loc in self:
            loc.child_internal_location_ids = self.search(
                [("id", "child_of", loc.id), ("usage", "=", "internal")]
            )

    @api.depends("usage")
    def _compute_replenish_location(self):
        for loc in self:
            if loc.usage != "internal":
                loc.replenish_location = False

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_is_empty(self, operator, value):
        # Only the positive operator is implemented; the ORM derives the negative
        # (is_empty = False) by negating this domain (see Field.search docs).
        if operator != "in":
            return NotImplemented
        stocked_location_ids = [
            location.id
            for (location,) in self.env["stock.quant"]._read_group(
                [("location_id.usage", "in", ["internal", "transit"])],
                ["location_id"],
                having=[("quantity:sum", ">", 0)],
            )
        ]
        return [("id", "not in", stocked_location_ids)]

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _child_of(self, other_location):
        self.ensure_one()
        # A record with no parent_path (unstored) is a child of nothing; a
        # missing/empty other_location (e.g. a ref resolved with
        # raise_if_not_found=False) is an ancestor of nothing.
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
        if not active:
            # One query for the whole set instead of a search per location.
            blocking_warehouse = self.env["stock.warehouse"].search(
                [
                    ("active", "=", True),
                    "|",
                    ("lot_stock_id", "in", self.ids),
                    ("view_location_id", "in", self.ids),
                ],
                limit=1,
            )
            if blocking_warehouse:
                location = (
                    blocking_warehouse.lot_stock_id
                    if blocking_warehouse.lot_stock_id in self
                    else blocking_warehouse.view_location_id
                )
                raise UserError(
                    _(
                        "You cannot archive location %(location)s because it is used by warehouse %(warehouse)s",
                        location=location.display_name,
                        warehouse=blocking_warehouse.display_name,
                    ),
                )

        # Despite its name, ``do_not_check_quant`` returns before the subtree
        # traversal below, suppressing the whole descendant cascade — this is what
        # stops the recursive write at the end of this method from re-cascading.
        if self.env.context.get("do_not_check_quant"):
            return
        # ``child_of`` returns self *and* every descendant, not just direct
        # children — the whole subtree is what (de)activates together.
        descendant_locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("id", "child_of", self.ids)])
        )
        # The stock check only blocks *deactivation*; skip it (and its
        # query) entirely when reactivating.
        if not active:
            internal_descendants = descendant_locations.filtered(
                lambda l: l.usage == "internal"
            )
            blocking_quants = self.env["stock.quant"].search(
                [
                    "&",
                    "|",
                    ("quantity", "!=", 0),
                    ("reserved_quantity", "!=", 0),
                    ("location_id", "in", internal_descendants.ids),
                ],
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
        Falls back to the first child location if self is a view location,
        otherwise returns self. Quantity is expected in the product's default
        UOM and is only used when no package is specified.
        """
        self = self._check_access_putaway()
        products = self.env.context.get("products", self.env["product.product"])
        products |= product
        package_type = self.env["stock.package.type"]
        if package:
            package_type = package.package_type_id
        elif packaging:
            package_type = packaging.package_type_id

        # The product's own category (empty when the products span several), plus
        # its ancestor chain — a rule targeting any of them applies here.
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
                bool(rule.category_id == leaf_category),  # exact category beats ancestor
                bool(rule.category_id),
            ),
            reverse=True,
        )

        putaway_location = None
        locations = self.env.context.get("locations")
        if not locations:
            locations = self.child_internal_location_ids
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
            # array_agg (not recordset) for the UoMs: recordset dedups, which
            # would drop rows when several lines share a UoM and misalign the
            # quantity<->UoM zip below.
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
        # Clamp a 0/negative or overflowing configured day into the month.
        day = max(self.company_id.annual_inventory_day, 1)
        day = min(day, calendar.monthrange(today.year, month)[1])
        annual_date = today.replace(month=month, day=day)
        if annual_date <= today:
            # This year's date has passed; roll to next year (re-clamp leap Feb).
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

    # ------------------------------------------------------------
    # VALIDATION METHODS
    # ------------------------------------------------------------

    def _check_access_putaway(self):
        return self

    def _check_can_be_used(
        self, product, quantity=0, package=None, location_qty=0, forecast_weight=None
    ):
        """Check if product/package can be stored in the location. Quantity
        should be in the product's default UoM; only used when no package is
        specified. ``forecast_weight`` may be supplied by the caller (e.g. when
        checking many candidate locations) to avoid recomputing it per location;
        when None it is computed from this location's quants and move lines."""
        self.ensure_one()
        # No storage category => no restriction to enforce.
        if not self.storage_category_id:
            return True
        if not self._check_new_product_policy(product, package):
            return False
        if forecast_weight is None:
            forecast_weight = self._get_weight(
                self.env.context.get("exclude_sml_ids", set()),
            )[self]["forecast_weight"]
        if package and package.package_type_id:
            return self._check_package_capacity(package, location_qty, forecast_weight)
        return self._check_product_capacity(
            product, quantity, location_qty, forecast_weight
        )

    def _check_new_product_policy(self, product, package):
        """Whether the storage category's ``allow_new_product`` rule permits
        storing this product/package here (True = allowed)."""
        self.ensure_one()
        policy = self.storage_category_id.allow_new_product
        if policy not in ("empty", "same"):
            return True
        positive_quant = self.quant_ids.filtered(
            lambda q: q.product_id.uom_id.compare(q.quantity, 0) > 0,
        )
        if policy == "empty":
            return not positive_quant
        # policy == "same": the location may hold a single product only.
        # For a package, `product` isn't set, so fall back to the context products.
        product = product or self.env.context.get("products")
        if (positive_quant and positive_quant.product_id != product) or len(product) > 1:
            return False
        return not self.env["stock.move.line"].search_count(
            [
                ("product_id", "!=", product.id),
                ("state", "not in", ("done", "cancel")),
                ("location_dest_id", "=", self.id),
            ],
            limit=1,
        )

    def _check_package_capacity(self, package, location_qty, forecast_weight):
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
        if storage_category.max_weight < forecast_weight + package_weight:
            return False
        package_capacity = storage_category.package_capacity_ids.filtered(
            lambda pc: pc.package_type_id == package.package_type_id
        )
        return not (package_capacity and location_qty >= package_capacity.quantity)

    def _check_product_capacity(self, product, quantity, location_qty, forecast_weight):
        """Enforce the storage category's max weight and per-product capacity for
        a bare-product move into this location (True = fits)."""
        self.ensure_one()
        storage_category = self.storage_category_id
        if storage_category.max_weight < forecast_weight + product.weight * quantity:
            return False
        product_capacity = storage_category.product_capacity_ids.filtered(
            lambda pc: pc.product_id == product,
        )
        if not product_capacity:
            return True
        # Reject a location already at capacity even if quantity is 0 (e.g. a new,
        # not yet filled-in move line), and any move that would exceed it.
        if location_qty >= product_capacity.quantity:
            return False
        return quantity + location_qty <= product_capacity.quantity

    def _check_company_not_changed(self, company_id):
        """A location's company is immutable once set; archive and recreate
        instead of moving it between companies."""
        if any(location.company_id.id != company_id for location in self):
            raise UserError(
                _(
                    "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                ),
            )

    def _check_usage_convertible(self, usage):
        """Block a usage change that would strand stock: a location can't become
        a view while it holds products, nor change type while it holds stock."""
        if usage == "view" and self.env["stock.quant"].search_count(
            [("location_id", "in", self.ids)],
            limit=1,
        ):
            raise UserError(
                _(
                    "This location's usage cannot be changed to view as it contains products."
                ),
            )
        modified_locations = self.filtered(lambda l: l.usage != usage)
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
        # Inter-company transit locations (and their descendants) also count as outgoing
        inter_comp_location = self.env.ref(
            "stock.stock_location_inter_company", raise_if_not_found=False
        )
        return self._child_of(inter_comp_location)

    def should_bypass_reservation(self):
        self.ensure_one()
        return self.usage in ("supplier", "customer", "inventory", "production")
