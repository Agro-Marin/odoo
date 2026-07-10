import logging
from collections import defaultdict, namedtuple

from odoo import api, fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.tools import ormcache
from odoo.tools.translate import LazyTranslate, _

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)


ROUTE_NAMES = {
    "one_step": _lt("Receive in 1 step (stock)"),
    "two_steps": _lt("Receive in 2 steps (input + stock)"),
    "three_steps": _lt("Receive in 3 steps (input + quality + stock)"),
    "ship_only": _lt("Deliver in 1 step (ship)"),
    "pick_ship": _lt("Deliver in 2 steps (pick + ship)"),
    "pick_pack_ship": _lt("Deliver in 3 steps (pick + pack + ship)"),
}

# The base warehouse picking types, in creation-sequence order (the order fixes
# each type's sequence offset, in_type_id first ... xdock_type_id last). Each
# value is the short code the type reuses as its ir.sequence code, its prefix
# segment and its barcode suffix. Keeping it here once stops
# _get_picking_type_create_values, _get_picking_type_update_values and
# _get_sequence_values from drifting apart. Modules add their own types by
# extending those three helpers directly.
WAREHOUSE_PICKING_TYPE_CODES = {
    "in_type_id": "IN",
    "qc_type_id": "QC",
    "store_type_id": "STOR",
    "int_type_id": "INT",
    "pick_type_id": "PICK",
    "pack_type_id": "PACK",
    "out_type_id": "OUT",
    "xdock_type_id": "XD",
}


class StockWarehouse(models.Model):
    _name = "stock.warehouse"
    _description = "Warehouse"
    _order = "sequence,id"
    _check_company_auto = True

    Routing = namedtuple("Routing", ["from_loc", "dest_loc", "picking_type", "action"])

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    name = fields.Char(
        string="Warehouse",
        required=True,
        default=lambda self: self._default_name(),
    )
    active = fields.Boolean(string="Active", default=True)
    sequence = fields.Integer(
        default=10,
        help="Gives the sequence of this line when displaying the warehouses.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
        help="The company is automatically set from your user preferences.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Address",
        default=lambda self: self.env.company.partner_id,
        check_company=True,
    )
    view_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="View Location",
        required=True,
        check_company=True,
        domain="[('usage', '=', 'view'), ('company_id', '=', company_id)]",
        index=True,
    )
    lot_stock_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location Stock",
        required=True,
        check_company=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
    )
    code = fields.Char(
        string="Short Name",
        required=True,
        size=5,
        help="Short name used to identify your warehouse",
    )
    route_ids = fields.Many2many(
        comodel_name="stock.route",
        relation="stock_route_warehouse",
        column1="warehouse_id",
        column2="route_id",
        string="Routes",
        check_company=True,
        domain="[('warehouse_selectable', '=', True), ('company_id', 'in', [False, company_id])]",
        copy=False,
        help="Defaults routes through the warehouse",
    )
    reception_steps = fields.Selection(
        selection=[
            ("one_step", "Receive and Store (1 step)"),
            ("two_steps", "Receive then Store (2 steps)"),
            ("three_steps", "Receive, Quality Control, then Store (3 steps)"),
        ],
        string="Incoming Shipments",
        required=True,
        default="one_step",
        help="Default incoming route to follow",
    )
    delivery_steps = fields.Selection(
        selection=[
            ("ship_only", "Deliver (1 step)"),
            ("pick_ship", "Pick then Deliver (2 steps)"),
            ("pick_pack_ship", "Pick, Pack, then Deliver (3 steps)"),
        ],
        string="Outgoing Shipments",
        required=True,
        default="ship_only",
        help="Default outgoing route to follow",
    )
    wh_input_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Input Location",
        check_company=True,
    )
    wh_qc_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Quality Control Location",
        check_company=True,
    )
    wh_output_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Output Location",
        check_company=True,
    )
    wh_pack_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Packing Location",
        check_company=True,
    )
    mto_pull_id = fields.Many2one(
        comodel_name="stock.rule", string="MTO rule", copy=False
    )
    pick_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Pick Type",
        check_company=True,
        copy=False,
    )
    pack_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Pack Type",
        check_company=True,
        copy=False,
    )
    out_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Out Type",
        check_company=True,
        copy=False,
    )
    in_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="In Type",
        check_company=True,
        copy=False,
    )
    int_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Internal Type",
        check_company=True,
        copy=False,
    )
    qc_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Quality Control Type",
        check_company=True,
        copy=False,
    )
    store_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Storage Type",
        check_company=True,
        copy=False,
    )
    xdock_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Cross Dock Type",
        check_company=True,
        copy=False,
    )
    reception_route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Receipt Route",
        ondelete="restrict",
        copy=False,
    )
    delivery_route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Delivery Route",
        ondelete="restrict",
        copy=False,
    )
    resupply_wh_ids = fields.Many2many(
        comodel_name="stock.warehouse",
        relation="stock_wh_resupply_table",
        column1="supplied_wh_id",
        column2="supplier_wh_id",
        string="Resupply From",
        help="Routes will be created automatically to resupply this warehouse from the warehouses ticked",
    )
    resupply_route_ids = fields.One2many(
        comodel_name="stock.route",
        inverse_name="supplied_wh_id",
        string="Resupply Routes",
        copy=False,
        help="Routes will be created for these resupply warehouses and you can select them on products and product categories",
    )

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    _warehouse_name_uniq = models.Constraint(
        "unique(name, company_id)",
        "The name of the warehouse must be unique per company!",
    )
    _warehouse_code_uniq = models.Constraint(
        "unique(code, company_id)",
        "The short name of the warehouse must be unique per company!",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        taken_names = defaultdict(set)
        taken_codes = defaultdict(set)
        for vals in vals_list:
            # Resolve the company up front (same default company_id uses) so
            # name/code/partner are generated even when the caller omits
            # company_id: defaults aren't injected into vals until super()
            # .create(), so otherwise `code` stays unset and the view location
            # below would be created with name=None (NOT NULL violation).
            company = (
                self.env["res.company"].browse(vals["company_id"])
                if vals.get("company_id")
                else self.env.company
            )
            vals.setdefault("company_id", company.id)
            if "name" not in vals:
                vals["name"] = self._generate_default_name(
                    company, taken_names[company.id]
                )
            if "code" not in vals:
                vals["code"] = self._generate_default_code(
                    company, taken_codes[company.id]
                )
            if "partner_id" not in vals:
                vals["partner_id"] = company.partner_id.id
            # Reserve this row's name/code (explicit or generated) so a later
            # sibling in the same batch can't be handed the same default
            # before the batch is flushed and the DB search can see it.
            if vals.get("name"):
                taken_names[company.id].add(vals["name"])
            if vals.get("code"):
                taken_codes[company.id].add(vals["code"])
            loc_vals = {
                "name": vals["code"],
                "usage": "view",
                "company_id": company.id,
            }
            vals["view_location_id"] = self.env["stock.location"].create(loc_vals).id
            sub_locations = self._get_locations_values(vals)
            for values in sub_locations.values():
                values["location_id"] = vals["view_location_id"]
                values["company_id"] = company.id
            # Create every sub-location in a single call rather than one query
            # each. dict + create() both preserve order, so zip pairs field to
            # its freshly created location.
            sub_records = (
                self.env["stock.location"]
                .with_context(active_test=False)
                .create(list(sub_locations.values()))
            )
            for field_name, location in zip(sub_locations, sub_records, strict=True):
                vals[field_name] = location.id

        warehouses = super().create(vals_list)

        for warehouse, vals in zip(warehouses, vals_list, strict=True):
            new_vals = warehouse._create_or_update_sequences_and_picking_types()
            warehouse.write(new_vals)  # TDE FIXME: use super ?
            # _create_or_update_route and _create_or_update_global_routes_rules
            # each persist their own field assignments in a single trailing
            # write, so there's nothing left for the caller to write back.
            warehouse._create_or_update_route()
            warehouse._create_or_update_global_routes_rules()

            warehouse.create_resupply_routes(warehouse.resupply_wh_ids)

            if vals.get("partner_id"):
                self._update_partner_data(vals["partner_id"], vals.get("company_id"))

            # warehouse_id wasn't set on these locations yet since the warehouse
            # didn't exist when they were created above
            view_location_id = self.env["stock.location"].browse(
                vals.get("view_location_id")
            )
            (
                view_location_id
                | view_location_id.with_context(active_test=False).child_ids
            ).write({"warehouse_id": warehouse.id})

        self._check_multiwarehouse_group()

        return warehouses

    def write(self, vals):
        if "company_id" in vals:
            for warehouse in self:
                if warehouse.company_id.id != vals["company_id"]:
                    raise UserError(
                        _(
                            "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                        )
                    )

        warehouses = self.with_context(active_test=False)
        warehouses._create_missing_locations(vals)

        if vals.get("reception_steps"):
            warehouses._update_location_reception(vals["reception_steps"])

        if vals.get("delivery_steps"):
            warehouses._update_location_delivery(vals["delivery_steps"])

        if vals.get("reception_steps") or vals.get("delivery_steps"):
            warehouses._update_reception_delivery_resupply(
                vals.get("reception_steps"), vals.get("delivery_steps")
            )

        if vals.get("resupply_wh_ids") and not vals.get("resupply_route_ids"):
            old_resupply_whs = {
                warehouse.id: warehouse.resupply_wh_ids for warehouse in warehouses
            }

        if vals.get("partner_id"):
            if vals.get("company_id"):
                warehouses._update_partner_data(
                    vals["partner_id"], vals.get("company_id")
                )
            else:
                for warehouse in self:
                    warehouse._update_partner_data(
                        vals["partner_id"], warehouse.company_id.id
                    )

        if vals.get("code") or vals.get("name"):
            warehouses._update_name_and_code(vals.get("name"), vals.get("code"))

        res = super().write(vals)

        # The refresh-trigger fields are a structural set, so resolve them once
        # from the cached helper instead of rebuilding the route values (and
        # calling get_rules_dict) per warehouse on every write. See
        # _get_route_trigger_fields.
        if warehouses:
            route_depends, global_depends, global_rule_keys = warehouses[
                :1
            ]._get_route_trigger_fields()
        else:
            route_depends = global_depends = global_rule_keys = frozenset()
        changed = vals.keys()
        # "code" isn't in any route's `depends` but picking type barcodes are
        # derived from it, so it still needs a picking-type refresh.
        refresh_picking_types = "code" in changed or not route_depends.isdisjoint(
            changed
        )
        refresh_routes = not route_depends.isdisjoint(changed)
        # Global routes (MTO, Buy, ...) refresh on their rules' `depends` or when
        # a global rule field (mto_pull_id, ...) is written directly.
        refresh_global = not self.env.context.get("stock_no_global_route_refresh") and (
            not global_depends.isdisjoint(changed)
            or not global_rule_keys.isdisjoint(changed)
        )

        for warehouse in warehouses:
            if refresh_picking_types:
                picking_type_vals = (
                    warehouse._create_or_update_sequences_and_picking_types()
                )
                if picking_type_vals:
                    warehouse.write(picking_type_vals)
            if refresh_routes:
                warehouse._create_or_update_route()
            if refresh_global:
                warehouse._create_or_update_global_routes_rules()

            if "active" in vals:
                warehouse._toggle_active(vals["active"], route_depends | global_depends)

        if vals.get("resupply_wh_ids") and not vals.get("resupply_route_ids"):
            for warehouse in warehouses:
                warehouse._sync_resupply_routes(old_resupply_whs[warehouse.id])

        if "active" in vals:
            self._check_multiwarehouse_group()

        return res

    def unlink(self):
        res = super().unlink()
        self._check_multiwarehouse_group()
        return res

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        taken_names = defaultdict(set)
        taken_codes = defaultdict(set)
        for warehouse, vals in zip(self, vals_list, strict=True):
            company = warehouse.company_id
            if "name" not in default:
                vals["name"] = self._unique_copy_name(
                    _("%s (copy)", warehouse.name), company, taken_names[company.id]
                )
            if "code" not in default:
                # A fresh unique code: the former constant "COPY" collided on the
                # second copy within a company (unique(code, company_id)).
                vals["code"] = self._generate_default_code(
                    company, taken_codes[company.id]
                )
            if vals.get("name"):
                taken_names[company.id].add(vals["name"])
            if vals.get("code"):
                taken_codes[company.id].add(vals["code"])
        return vals_list

    @ormcache()
    def _sub_location_field_names(self):
        """Names of the warehouse Many2one fields that ``_get_locations_values``
        creates sub-locations for — the base ones (Stock, Input, QC, Output,
        Packing) plus any added by installed modules (e.g. mrp's pbm/sam).

        Cached because the set is structural: it only changes when a module
        extending ``_get_locations_values`` is (un)installed, which reloads the
        registry and clears this cache. Lets ``_create_missing_locations`` check
        for missing locations on every write without a barcode search per
        location each time.
        """
        return tuple(self._get_locations_values({}))

    @ormcache()
    def _get_route_depend_fields(self):
        """Warehouse field names whose modification must refresh the
        reception/delivery (and module-added) routes and picking types — the
        ``depends`` of ``_get_routes_values``.

        Structural set (the names come from *static* ``depends`` lists), hence
        cached: it only changes when a module extending ``_get_routes_values`` is
        (un)installed, which reloads the registry and clears this cache. See
        ``_sub_location_field_names`` for why keying only on the model is safe.
        """
        return frozenset(self._collect_depends(self._get_routes_values()))

    @ormcache()
    def _get_global_trigger_fields(self):
        """The global-route trigger fields, as a
        ``(global_depends, global_rule_keys)`` pair:

        - ``global_depends``: the ``depends`` of
          ``_generate_global_route_rules_values``.
        - ``global_rule_keys``: the global rule ``Many2one`` field names
          themselves (writing one directly also warrants a refresh).

        The *unfiltered* ``_generate_global_route_rules_values`` is used on
        purpose: an over-inclusive trigger set only risks a redundant (and
        idempotent) refresh, whereas a missing field would skip a needed one.

        Structural, hence cached — but ``_generate_global_route_rules_values``
        can ``raise`` on a warehouse whose delivery chain has no stock-origin
        rule. The raise propagates *before* ormcache stores anything, so a
        misconfigured warehouse never poisons this cache for its healthy
        siblings: the caller turns the raise into a base-globals fallback, and
        the next successful call caches the real set. (The old combined helper
        cached the fallback registry-wide, letting one broken warehouse suppress
        global-route refreshes for all.)
        """
        global_values = self._generate_global_route_rules_values()
        return (
            frozenset(self._collect_depends(global_values)),
            frozenset(global_values),
        )

    def _get_route_trigger_fields(self):
        """Return ``(route_depends, global_depends, global_rule_keys)``: the
        warehouse fields whose modification must refresh routes, rules and
        picking types on ``write``. Composes the two cached structural helpers so
        ``write`` can decide whether a refresh is needed without rebuilding the
        route values (and without calling ``get_rules_dict`` / resolving partner
        & production locations) on every write.

        The global part is guarded: ``_generate_global_route_rules_values`` can
        ``raise`` on a warehouse whose delivery chain has no stock-origin rule.
        Rather than abort an unrelated write (e.g. a rename), fall back to the
        base-known globals. This fallback lives here, not in the cached helper,
        so it is never cached and can't leak onto other warehouses (see
        ``_get_global_trigger_fields``).
        """
        route_depends = self._get_route_depend_fields()
        try:
            global_depends, global_rule_keys = self._get_global_trigger_fields()
        except UserError:
            _logger.warning(
                "Could not resolve global route rules while computing warehouse "
                "route trigger fields; falling back to base globals.",
            )
            global_depends = frozenset({"delivery_steps"})
            global_rule_keys = frozenset({"mto_pull_id"})
        return route_depends, global_depends, global_rule_keys

    # ------------------------------------------------------------
    # DEFAULT METHODS
    # ------------------------------------------------------------

    def _default_name(self):
        return self._generate_default_name(self.env.company)

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("company_id")
    def _onchange_company_id(self):
        group_user = self.env.ref("base.group_user")
        group_stock_multi_warehouses = self.env.ref(
            "stock.group_stock_multi_warehouses"
        )
        group_stock_multi_location = self.env.ref("stock.group_stock_multi_locations")
        if (
            group_stock_multi_warehouses not in group_user.implied_ids
            and group_stock_multi_location not in group_user.implied_ids
        ):
            return {
                "warning": {
                    "title": _("Warning"),
                    "message": _(
                        "Creating a new warehouse will automatically activate the Storage Locations setting"
                    ),
                }
            }
        return None

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _toggle_active(self, active, reactivate_depends):
        """(Un)archive the warehouse together with its picking types, locations,
        routes and rules to match ``active``.

        Refuses to archive while there are ongoing operations, or when a picking
        type outside this warehouse still points at one of its locations. On
        reactivation, ``reactivate_depends`` (the route/global trigger fields) is
        re-written on the warehouse so ``write`` rebuilds its dependent records.
        """
        self.ensure_one()
        PickingType = self.env["stock.picking.type"]
        picking_types = PickingType.with_context(active_test=False).search(
            [("warehouse_id", "=", self.id)]
        )
        moves = self.env["stock.move"].search(
            [
                ("picking_type_id", "in", picking_types.ids),
                ("state", "not in", ("done", "cancel")),
            ]
        )
        if moves:
            raise UserError(
                _(
                    "You still have ongoing operations for operation types %(operations)s in warehouse %(warehouse)s",
                    operations=moves.mapped("picking_type_id.name"),
                    warehouse=self.name,
                )
            )
        picking_types.write({"active": active})
        locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("location_id", "child_of", self.view_location_id.id)])
        )
        # A foreign picking type blocks archiving if EITHER its default source or
        # destination sits inside this warehouse (matching the error below):
        # archiving those locations would leave it pointing at an archived one.
        # The former all-AND domain only caught types with *both* endpoints
        # inside, letting src-only / dest-only references dangle past archive.
        picking_type_using_locations = PickingType.search(
            [
                "|",
                ("default_location_src_id", "in", locations.ids),
                ("default_location_dest_id", "in", locations.ids),
                ("id", "not in", picking_types.ids),
            ]
        )
        if picking_type_using_locations:
            raise UserError(
                _(
                    "%(operations)s have default source or destination locations within warehouse %(warehouse)s, therefore you cannot archive it.",
                    operations=picking_type_using_locations.mapped("name"),
                    warehouse=self.name,
                )
            )
        self.view_location_id.write({"active": active})

        rules = (
            self.env["stock.rule"]
            .with_context(active_test=False)
            .search([("warehouse_id", "=", self.id)])
        )
        # Don't archive routes shared with other warehouses.
        self.route_ids.filtered(lambda r: len(r.warehouse_ids) == 1).write(
            {"active": active}
        )
        rules.write({"active": active})

        if active:
            # Re-writing these fields on itself re-triggers the write() refresh
            # logic that (re)activates the dependent routes, rules, picking types
            # and locations.
            values = {
                "resupply_route_ids": [
                    (4, route.id) for route in self.resupply_route_ids
                ]
            }
            for depend in reactivate_depends:
                values[depend] = self[depend]
            self.write(values)

    def _sync_resupply_routes(self, previous_resupply_whs):
        """Reflect a change of ``resupply_wh_ids`` on the resupply routes:
        (re)create routes to newly added supplier warehouses (reusing an
        archived one when present) and archive routes to removed ones.
        ``previous_resupply_whs`` is the ``resupply_wh_ids`` value before write.
        """
        self.ensure_one()
        Route = self.env["stock.route"]
        new_resupply_whs = self.resupply_wh_ids
        to_add = new_resupply_whs - previous_resupply_whs
        to_remove = previous_resupply_whs - new_resupply_whs
        if to_add:
            existing_routes = Route.search(
                [
                    ("supplied_wh_id", "=", self.id),
                    ("supplier_wh_id", "in", to_add.ids),
                    ("active", "=", False),
                ]
            )
            existing_routes.action_unarchive()
            remaining_to_add = to_add - existing_routes.supplier_wh_id
            if remaining_to_add:
                self.create_resupply_routes(remaining_to_add)
        if to_remove:
            to_disable_route_ids = Route.search(
                [
                    ("supplied_wh_id", "=", self.id),
                    ("supplier_wh_id", "in", to_remove.ids),
                    ("active", "=", True),
                ]
            )
            to_disable_route_ids.action_archive()

    def _existing_warehouse_values(self, field_name, company, taken=()):
        """Return the set of ``field_name`` values already used by ``company``'s
        warehouses (archived included) unioned with ``taken`` — the values
        reserved earlier in the same, not-yet-flushed, create/copy batch that the
        DB search can't see yet.

        Single source shared by the name/code generators so they de-duplicate
        against the same population and never collide with the
        ``unique(<field>, company_id)`` constraints.
        """
        return set(taken) | set(
            self.env["stock.warehouse"]
            .with_context(active_test=False)
            .search([("company_id", "=", company.id)])
            .mapped(field_name)
        )

    def _generate_default_name(self, company, taken=()):
        """Return a unique warehouse name for ``company``: the company name for
        the first warehouse, then a name suffixed with an incrementing counter.
        Shared by the field default and ``create`` so both paths agree and
        never collide with the ``unique(name, company_id)`` constraint.

        ``taken`` reserves names already assigned earlier in the same, not yet
        flushed, create/copy batch — which the DB search can't see — so
        sibling records with defaulted names don't collide with each other.
        """
        existing = self._existing_warehouse_values("name", company, taken)
        if not existing:
            return company.name
        counter = len(existing) + 1
        while True:
            candidate = "%s - warehouse # %s" % (company.name, counter)
            if candidate not in existing:
                return candidate
            counter += 1

    def _generate_default_code(self, company, taken=()):
        """Return a unique 5-char short name for ``company``, derived from the
        company name and de-duplicated against existing warehouse codes so it
        never collides with the ``unique(code, company_id)`` constraint.

        ``taken`` reserves codes already assigned earlier in the same, not yet
        flushed, create/copy batch (see ``_generate_default_name``).
        """
        base = ((company.name or "WH")[:5] or "WH").upper()
        existing = self._existing_warehouse_values("code", company, taken)
        if base not in existing:
            return base
        # Keep within the 5-char limit by trimming room for the numeric suffix.
        for counter in range(2, 100000):
            suffix = str(counter)
            candidate = base[: 5 - len(suffix)] + suffix
            if candidate not in existing:
                return candidate
        raise UserError(
            _(
                "Unable to generate a unique short name for a warehouse in %s.",
                company.display_name,
            )
        )

    @api.model
    def _warehouse_redirect_warning(self):
        if (
            not self.env.registry.ready
        ):  # don't raise warning during module installation
            return
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError(
                self.env._(
                    "Please contact your administrator to configure your warehouse."
                )
            )
        warehouse_action = self.env.ref("stock.action_stock_warehouse")
        msg = _(
            "Please create a warehouse for company %s.", self.env.company.display_name
        )
        raise RedirectWarning(msg, warehouse_action.id, _("Go to Warehouses"))

    def _unique_copy_name(self, base, company, taken=()):
        """Return the copy name ``base`` made unique for ``company`` against
        existing warehouses and ``taken`` (siblings copied in the same batch).
        """
        existing = self._existing_warehouse_values("name", company, taken)
        if base not in existing:
            return base
        counter = 2
        while True:
            candidate = "%s %s" % (base, counter)
            if candidate not in existing:
                return candidate
            counter += 1

    @api.model
    def _collect_depends(self, values_by_key):
        """Flatten the ``depends`` lists of a ``{key: {'depends': [...], ...}}``
        mapping (as returned by ``_get_routes_values`` /
        ``_get_global_route_rules_values``) into a set of warehouse field names
        whose modification should trigger a refresh of those routes/rules.
        """
        return {
            depend
            for values in values_by_key.values()
            for depend in values.get("depends", [])
        }

    def _check_multiwarehouse_group(self):
        cnt_by_company = (
            self.env["stock.warehouse"]
            .sudo()
            ._read_group(
                [("active", "=", True)], ["company_id"], aggregates=["__count"]
            )
        )
        if cnt_by_company:
            max_count = max(count for company, count in cnt_by_company)
            group_user = self.env.ref("base.group_user")
            group_stock_multi_warehouses = self.env.ref(
                "stock.group_stock_multi_warehouses"
            )
            group_stock_multi_locations = self.env.ref(
                "stock.group_stock_multi_locations"
            )
            if (
                max_count <= 1
                and group_stock_multi_warehouses in group_user.implied_ids
            ):
                group_user.write(
                    {"implied_ids": [(3, group_stock_multi_warehouses.id)]}
                )
                group_stock_multi_warehouses.write(
                    {"user_ids": [(3, user.id) for user in group_user.all_user_ids]}
                )
            if (
                max_count > 1
                and group_stock_multi_warehouses not in group_user.implied_ids
            ):
                if group_stock_multi_locations not in group_user.implied_ids:
                    self.env["res.config.settings"].create(
                        {
                            "group_stock_multi_locations": True,
                        }
                    ).execute()
                group_user.write(
                    {
                        "implied_ids": [
                            (4, group_stock_multi_warehouses.id),
                            (4, group_stock_multi_locations.id),
                        ]
                    }
                )

    @api.model
    def _update_partner_data(self, partner_id, company_id):
        if not partner_id:
            return
        company = (
            self.env["res.company"].browse(company_id)
            if company_id
            else self.env.company
        )
        transit_loc = company.internal_transit_location_id.id
        # property_stock_customer/supplier are company-dependent; write them in
        # that company's context so the value lands on the right property.
        self.env["res.partner"].browse(partner_id).with_company(company).write(
            {
                "property_stock_customer": transit_loc,
                "property_stock_supplier": transit_loc,
            }
        )

    def _create_or_update_sequences_and_picking_types(self):
        """Create the warehouse's picking types (with a dedicated sequence)
        if they don't exist yet, otherwise update them via
        _get_picking_type_update_values.
        """
        self.ensure_one()
        IrSequenceSudo = self.env["ir.sequence"].sudo()
        PickingType = self.env["stock.picking.type"]

        # Recycle colors 0-11 across this company's warehouses instead of growing
        # unbounded. Scoped to the company so the search stays bounded (a handful
        # of picking types) rather than scanning every warehouse in the database.
        all_used_colors = [
            res["color"]
            for res in PickingType.search_read(
                [
                    ("warehouse_id", "!=", False),
                    ("color", "!=", False),
                    ("company_id", "=", self.company_id.id),
                ],
                ["color"],
                order="color",
            )
        ]
        available_colors = [c for c in range(12) if c not in all_used_colors]
        color = available_colors[0] if available_colors else 0

        warehouse_data = {}
        sequence_data = self._get_sequence_values()

        # New picking types are sequenced after every existing one, across all warehouses.
        max_sequence = self.env["stock.picking.type"].search_read(
            [("sequence", "!=", False)], ["sequence"], limit=1, order="sequence desc"
        )
        max_sequence = (max_sequence and max_sequence[0]["sequence"]) or 0

        data = self._get_picking_type_update_values()
        create_data, max_sequence = self._get_picking_type_create_values(max_sequence)

        for picking_type, values in data.items():
            if self[picking_type]:
                self[picking_type].sudo().sequence_id.write(
                    {"company_id": self.company_id.id}
                )
                self[picking_type].write(values)
            else:
                values.update(create_data[picking_type])
                existing_sequence = IrSequenceSudo.search_count(
                    [
                        ("company_id", "=", sequence_data[picking_type]["company_id"]),
                        ("name", "=", sequence_data[picking_type]["name"]),
                    ],
                    limit=1,
                )
                sequence = IrSequenceSudo.create(sequence_data[picking_type])
                if existing_sequence:
                    sequence.name = _(
                        "%(name)s (copy)(%(id)s)",
                        name=sequence.name,
                        id=str(sequence.id),
                    )
                values.update(
                    warehouse_id=self.id, color=color, sequence_id=sequence.id
                )
                warehouse_data[picking_type] = PickingType.create(values).id

        if "out_type_id" in warehouse_data:
            PickingType.browse(warehouse_data["out_type_id"]).write(
                {"return_picking_type_id": warehouse_data.get("in_type_id", False)}
            )
        if "in_type_id" in warehouse_data:
            PickingType.browse(warehouse_data["in_type_id"]).write(
                {"return_picking_type_id": warehouse_data.get("out_type_id", False)}
            )
        return warehouse_data

    def _create_or_update_global_routes_rules(self):
        """Some rules are not specific to a warehouse(e.g MTO, Buy, ...)
        however they contain rule(s) for a specific warehouse. This method will
        update the rules contained in global routes in order to make them match
        with the wanted reception, delivery,... steps.
        """
        new_rule_ids = {}
        for rule_field, rule_details in self._get_global_route_rules_values().items():
            values = rule_details.get("update_values", {})
            if self[rule_field]:
                self[rule_field].write(values)
            else:
                values.update(rule_details["create_values"])
                values.update({"warehouse_id": self.id})
                new_rule_ids[rule_field] = self.env["stock.rule"].create(values).id
        if new_rule_ids:
            # Persist every freshly-created global rule in one write. The skip
            # context stops that write from re-triggering this refresh: those
            # Many2one fields are global-rule triggers (a *user* editing one
            # refreshes), but here we set them and the rules are already current,
            # so a re-entrant refresh would just rebuild get_rules_dict and
            # rewrite identical values.
            self.with_context(stock_no_global_route_refresh=True).write(new_rule_ids)
        return True

    def _find_or_create_global_route(
        self,
        xml_id,
        route_name,
        create=True,
        raise_if_not_found=False,
    ):
        """return a route record set from an xml_id or its name."""
        data_route = route = self.env.ref(xml_id, raise_if_not_found=False)
        company = self.company_id[:1] or self.env.company
        if not route or (
            route.sudo().company_id and route.sudo().company_id != company
        ):
            route = (
                self.env["stock.route"]
                .with_context(active_test=False)
                .search(
                    [
                        # Anchored match (=like, no wildcards) so a route whose
                        # name merely *contains* route_name — e.g. "…(MTO) 2" for
                        # "…(MTO)" — isn't picked up as the generic route.
                        ("name", "=like", route_name),
                        ("company_id", "in", [False, company.id]),
                    ],
                    order="company_id",
                    limit=1,
                )
            )
        if not route:
            if raise_if_not_found:
                raise UserError(_("Can't find any generic route %s.", route_name))
            if data_route and create:
                route = data_route.copy(
                    {
                        "name": route_name,
                        "company_id": company.id,
                        "rule_ids": False,
                    },
                )
        return route

    def _get_global_route_rules_values(self):
        """Used by _create_or_update_global_routes_rules. Returns a dict keyed
        by the rule field name (e.g. 'mto_pull_id') to create/update, each
        mapping to:
            - depends: warehouse fields that, when written, should trigger an
              update of this rule.
            - create_values: values used to create the rule if it doesn't exist.
            - update_values: values used to update the rule otherwise.
        """
        vals = self._generate_global_route_rules_values()
        # `route_id` might be `False` if the user has deleted it, in such case we
        # should simply ignore the rule
        return {
            k: v
            for k, v in vals.items()
            if v.get("create_values", {}).get("route_id", True)
            and v.get("update_values", {}).get("route_id", True)
        }

    def _generate_global_route_rules_values(self):
        # The MTO rule always starts from stock, so pick the delivery step
        # whose source is lot_stock_id regardless of its position in the chain.
        delivery_rules = self.get_rules_dict()[self.id][self.delivery_steps]
        rule = next(
            (r for r in delivery_rules if r.from_loc == self.lot_stock_id), None
        )
        if not rule:
            raise UserError(
                _(
                    "The delivery configuration of warehouse %s has no rule "
                    "starting from its stock location, so its MTO rule can't be "
                    "generated.",
                    self.display_name,
                )
            )
        location_id = rule.from_loc
        location_dest_id = rule.dest_loc
        picking_type_id = rule.picking_type
        return {
            "mto_pull_id": {
                "depends": ["delivery_steps"],
                "create_values": {
                    "active": True,
                    "procure_method": "make_to_order",
                    "company_id": self.company_id.id,
                    "action": "pull",
                    "auto": "manual",
                    "propagate_carrier": True,
                    "route_id": self._find_or_create_global_route(
                        "stock.route_warehouse0_mto", _("Replenish on Order (MTO)")
                    ).id,
                },
                "update_values": {
                    "name": self._format_rulename(location_id, location_dest_id, "MTO"),
                    "location_dest_id": location_dest_id.id,
                    "location_src_id": location_id.id,
                    "picking_type_id": picking_type_id.id,
                },
            }
        }

    def _create_or_update_route(self):
        """Create or update the warehouse's routes and their rules.
        For each route field returned by _get_routes_values, resolve its rules
        via get_rules_dict (matched on 'routing_key') and let
        _find_existing_rule_or_create reuse or recreate them.

        Every route Many2one this (re)creates, plus the selectable routes added
        to ``route_ids``, is persisted in one trailing write rather than a write
        per assignment — collapsing several re-entrant warehouse writes (each
        paying a _check_company pass over ~20 relational fields) into one.
        """
        self.ensure_one()
        routes = []
        field_vals = {}
        rules_dict = self.get_rules_dict()
        for route_field, route_data in self._get_routes_values().items():
            if self[route_field]:
                route = self[route_field]
                if "route_update_values" in route_data:
                    route.write(route_data["route_update_values"])
                # Deactivate old rules; _find_existing_rule_or_create below will
                # reactivate the ones still needed and create any missing one.
                route.rule_ids.write({"active": False})
            else:
                if "route_update_values" in route_data:
                    route_data["route_create_values"].update(
                        route_data["route_update_values"]
                    )
                route = self.env["stock.route"].create(
                    route_data["route_create_values"]
                )
                field_vals[route_field] = route.id
            routing_key = route_data.get("routing_key")
            rules = rules_dict[self.id][routing_key]
            if "rules_values" in route_data:
                route_data["rules_values"].update({"route_id": route.id})
            else:
                route_data["rules_values"] = {"route_id": route.id}
            rules_list = self._get_rule_values(rules, values=route_data["rules_values"])
            self._find_existing_rule_or_create(rules_list)
            if route_data["route_create_values"].get(
                "warehouse_selectable", False
            ) or route_data.get("route_update_values", {}).get(
                "warehouse_selectable", False
            ):
                routes.append(route)
        field_vals["route_ids"] = [(4, route.id) for route in routes]
        self.write(field_vals)
        return field_vals

    def _get_routes_values(self):
        """Return the warehouse's own routes (reception_route_id and
        delivery_route_id) to create/update.
        - The key is the route field name (Many2one on the warehouse).
        - routing_key: matches the corresponding entry in get_rules_dict, used
          to generate the route's rules.
        - route_create_values: values used to create the route if the Many2one
          isn't set yet.
        - route_update_values: values used to update the route when a field
          listed in 'depends' changes.
        - rules_values: values added to the routing to create the route's rules.
        """
        return {
            "reception_route_id": {
                "routing_key": self.reception_steps,
                "depends": ["reception_steps"],
                "route_update_values": {
                    "name": self._format_routename(route_type=self.reception_steps),
                    "active": self.active,
                },
                "route_create_values": {
                    "product_categ_selectable": True,
                    "warehouse_selectable": True,
                    "product_selectable": False,
                    "company_id": self.company_id.id,
                    "sequence": 50,
                },
                "rules_values": {
                    "active": True,
                    "propagate_cancel": True,
                },
            },
            "delivery_route_id": {
                "routing_key": self.delivery_steps,
                "depends": ["delivery_steps"],
                "route_update_values": {
                    "name": self._format_routename(route_type=self.delivery_steps),
                    "active": self.active,
                },
                "route_create_values": {
                    "product_categ_selectable": True,
                    "warehouse_selectable": True,
                    "product_selectable": False,
                    "company_id": self.company_id.id,
                    "sequence": 60,
                },
                "rules_values": {"active": True, "propagate_carrier": True},
            },
        }

    def _get_receive_routes_values(self, installed_depends):
        """Same as _get_routes_values' reception_route_id, but forces
        'procure_method': 'make_to_order' on the rules instead of letting
        get_rules_dict default the first rule to make_to_stock. Used by modules
        that extend stock with actions able to trigger the receive MTO rules;
        meant to be used together with _get_receive_rules_dict().

        installed_depends: extra warehouse field (a module's install/enable
        boolean) that should also trigger a reception route update.
        """
        return {
            "reception_route_id": {
                "routing_key": self.reception_steps,
                "depends": ["reception_steps", installed_depends],
                "route_update_values": {
                    "name": self._format_routename(route_type=self.reception_steps),
                    "active": self.active,
                },
                "route_create_values": {
                    "product_categ_selectable": True,
                    "warehouse_selectable": True,
                    "product_selectable": False,
                    "company_id": self.company_id.id,
                    "sequence": 9,
                },
                "rules_values": {
                    "active": True,
                    "propagate_cancel": True,
                    "procure_method": "make_to_order",
                },
            }
        }

    def _find_existing_rule_or_create(self, rules_list):
        """Reuse the rule matching each entry's routing identity if one exists
        (reactivating it when archived), otherwise create it.

        The match ignores ``active`` on purpose: matching only archived rules
        (as it used to) would duplicate an already-active rule of the same
        identity. Ignoring ``active`` makes a second call a no-op, so it no
        longer relies on the caller having archived stale rules first.
        """
        Rule = self.env["stock.rule"]
        to_create = []
        for rule_vals in rules_list:
            existing_rule = Rule.with_context(active_test=False).search(
                [
                    ("picking_type_id", "=", rule_vals["picking_type_id"]),
                    ("location_src_id", "=", rule_vals["location_src_id"]),
                    ("location_dest_id", "=", rule_vals["location_dest_id"]),
                    ("route_id", "=", rule_vals["route_id"]),
                    ("action", "=", rule_vals["action"]),
                ],
                limit=1,
            )
            if not existing_rule:
                to_create.append(rule_vals)
            elif not existing_rule.active:
                existing_rule.active = True
        # Batch the creates: one INSERT instead of one query per missing rule.
        if to_create:
            Rule.create(to_create)

    def _get_locations_values(self, vals, code=False):
        """Return create/update values for the warehouse's sub-locations
        (Stock, Input, Quality Control, Output, Packing Zone), activating each
        one depending on the reception/delivery steps.
        """
        # Resolve every step/company default the values may omit in a single
        # default_get instead of one call per key.
        def_values = self.default_get(
            ["reception_steps", "delivery_steps", "company_id"]
        )
        reception_steps = vals.get("reception_steps", def_values["reception_steps"])
        delivery_steps = vals.get("delivery_steps", def_values["delivery_steps"])
        code = vals.get("code") or code or ""
        code = code.replace(" ", "").upper()
        company_id = vals.get("company_id", def_values["company_id"])
        return {
            "lot_stock_id": {
                "name": _("Stock"),
                "active": True,
                "usage": "internal",
                "replenish_location": True,
                "barcode": self._valid_barcode(code + "STOCK", company_id),
            },
            "wh_input_stock_loc_id": {
                "name": _("Input"),
                "active": reception_steps != "one_step",
                "usage": "internal",
                "barcode": self._valid_barcode(code + "INPUT", company_id),
            },
            "wh_qc_stock_loc_id": {
                "name": _("Quality Control"),
                "active": reception_steps == "three_steps",
                "usage": "internal",
                "barcode": self._valid_barcode(code + "QUALITY", company_id),
            },
            "wh_output_stock_loc_id": {
                "name": _("Output"),
                "active": delivery_steps != "ship_only",
                "usage": "internal",
                "barcode": self._valid_barcode(code + "OUTPUT", company_id),
            },
            "wh_pack_stock_loc_id": {
                "name": _("Packing Zone"),
                "active": delivery_steps == "pick_pack_ship",
                "usage": "internal",
                "barcode": self._valid_barcode(code + "PACKING", company_id),
            },
        }

    def _valid_barcode(self, barcode, company_id):
        location = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search(
                [("barcode", "=", barcode), ("company_id", "=", company_id)], limit=1
            )
        )
        if location:
            # Don't silently swallow the collision: a sub-location left without a
            # barcode is easy to miss and confusing to debug later.
            _logger.warning(
                "Barcode %s is already used by location %s; the new warehouse "
                "location will be created without a barcode.",
                barcode,
                location.display_name,
            )
            return False
        return barcode

    def _create_missing_locations(self, vals):
        """It could happen that the user delete a mandatory location or a
        module with new locations was installed after some warehouses creation.
        In this case, this function will create missing locations in order to
        avoid mistakes during picking types and rules creation.
        """
        location_fields = self._sub_location_field_names()
        for warehouse in self:
            # Fast path: skip building sub-location values (a barcode search per
            # location) when every sub-location already exists or is set
            # explicitly — the common case on every write(). The cached field
            # list also covers module-added locations (e.g. mrp's pbm/sam).
            if all(warehouse[field] or field in vals for field in location_fields):
                continue
            company_id = vals.get("company_id", warehouse.company_id.id)
            sub_locations = warehouse._get_locations_values(
                dict(vals, company_id=company_id), warehouse.code
            )
            missing_location = {}
            for location, location_values in sub_locations.items():
                if not warehouse[location] and location not in vals:
                    location_values["location_id"] = vals.get(
                        "view_location_id", warehouse.view_location_id.id
                    )
                    location_values["company_id"] = company_id
                    missing_location[location] = (
                        self.env["stock.location"].create(location_values).id
                    )
            if missing_location:
                warehouse.write(missing_location)

    def create_resupply_routes(self, supplier_warehouses):
        # Reads self.company_id / lot_stock_id / in_type_id as scalars and
        # builds routes owned by a single supplied warehouse.
        self.ensure_one()
        Route = self.env["stock.route"]
        Rule = self.env["stock.rule"]

        # `output_location` is (re)derived per supplier warehouse inside the loop
        # below, so there's no warehouse-level output location to compute here.
        internal_transit_location, external_transit_location = (
            self._get_transit_locations()
        )

        for supplier_wh in supplier_warehouses:
            transit_location = (
                internal_transit_location
                if supplier_wh.company_id == self.company_id
                else external_transit_location
            )
            if not transit_location:
                continue
            transit_location.active = True
            output_location = (
                supplier_wh.lot_stock_id
                if supplier_wh.delivery_steps == "ship_only"
                else supplier_wh.wh_output_stock_loc_id
            )
            # The leg from the supplier's output location to the transit location
            # feeds both the extra MTO rule and the inter-warehouse pull rule.
            output_to_transit = self.Routing(
                output_location, transit_location, supplier_wh.out_type_id, "pull"
            )
            # Create extra MTO rule (only for 'ship only' because in the other cases MTO rules already exists)
            if supplier_wh.delivery_steps == "ship_only":
                mto_vals = supplier_wh._get_global_route_rules_values().get(
                    "mto_pull_id"
                )
                # mto_vals is absent when the MTO route can't be resolved (user
                # deleted it): skip the extra rule rather than crashing on None.
                if mto_vals:
                    values = mto_vals["create_values"]
                    mto_rule_val = supplier_wh._get_rule_values(
                        [output_to_transit], values, name_suffix="MTO"
                    )
                    Rule.create(mto_rule_val[0])

            inter_wh_route = Route.create(
                self._get_inter_warehouse_route_values(supplier_wh)
            )

            pull_rules_list = supplier_wh._get_supply_pull_rules_values(
                [output_to_transit],
                values={"route_id": inter_wh_route.id, "location_dest_from_rule": True},
            )
            if supplier_wh.delivery_steps != "ship_only":
                # Replenish from Output location
                pull_rules_list += supplier_wh._get_supply_pull_rules_values(
                    [
                        self.Routing(
                            supplier_wh.lot_stock_id,
                            output_location,
                            supplier_wh.pick_type_id,
                            "pull",
                        )
                    ],
                    values={"route_id": inter_wh_route.id},
                )
            pull_rules_list += self._get_supply_pull_rules_values(
                [
                    self.Routing(
                        transit_location, self.lot_stock_id, self.in_type_id, "pull"
                    )
                ],
                values={"route_id": inter_wh_route.id},
            )
            # One batched INSERT instead of one query per rule.
            Rule.create(pull_rules_list)

    # Routing tools
    # ------------------------------------------------------------

    def _get_input_output_locations(self, reception_steps, delivery_steps):
        return (
            (
                self.lot_stock_id
                if reception_steps == "one_step"
                else self.wh_input_stock_loc_id
            ),
            (
                self.lot_stock_id
                if delivery_steps == "ship_only"
                else self.wh_output_stock_loc_id
            ),
        )

    def _get_transit_locations(self):
        return (
            self.company_id.internal_transit_location_id,
            self.env.ref("stock.stock_location_inter_company", raise_if_not_found=False)
            or self.env["stock.location"],
        )

    @api.model
    def _get_partner_locations(self):
        """returns a tuple made of the browse record of customer location and the browse record of supplier location"""
        Location = self.env["stock.location"]
        customer_loc = self.env.ref(
            "stock.stock_location_customers", raise_if_not_found=False
        )
        supplier_loc = self.env.ref(
            "stock.stock_location_suppliers", raise_if_not_found=False
        )
        if not customer_loc:
            customer_loc = Location.search([("usage", "=", "customer")], limit=1)
        if not supplier_loc:
            supplier_loc = Location.search([("usage", "=", "supplier")], limit=1)
        if not customer_loc and not supplier_loc:
            raise UserError(_("Can't find any customer or supplier location."))
        return customer_loc, supplier_loc

    def _get_route_name(self, route_type):
        return self.env._(ROUTE_NAMES[route_type])  # pylint: disable=gettext-variable

    def get_rules_dict(self):
        """Define the rules source/destination locations, picking_type and
        action needed for each warehouse route configuration.
        """
        customer_loc, supplier_loc = self._get_partner_locations()
        return {
            warehouse.id: {
                "one_step": [
                    self.Routing(
                        supplier_loc,
                        warehouse.lot_stock_id,
                        warehouse.in_type_id,
                        "pull",
                    )
                ],
                "two_steps": [
                    self.Routing(
                        supplier_loc,
                        warehouse.lot_stock_id,
                        warehouse.in_type_id,
                        "pull",
                    ),
                    self.Routing(
                        warehouse.wh_input_stock_loc_id,
                        warehouse.lot_stock_id,
                        warehouse.store_type_id,
                        "push",
                    ),
                ],
                "three_steps": [
                    self.Routing(
                        supplier_loc,
                        warehouse.lot_stock_id,
                        warehouse.in_type_id,
                        "pull",
                    ),
                    self.Routing(
                        warehouse.wh_input_stock_loc_id,
                        warehouse.wh_qc_stock_loc_id,
                        warehouse.qc_type_id,
                        "push",
                    ),
                    self.Routing(
                        warehouse.wh_qc_stock_loc_id,
                        warehouse.lot_stock_id,
                        warehouse.store_type_id,
                        "push",
                    ),
                ],
                "ship_only": [
                    self.Routing(
                        warehouse.lot_stock_id,
                        customer_loc,
                        warehouse.out_type_id,
                        "pull",
                    )
                ],
                "pick_ship": [
                    self.Routing(
                        warehouse.lot_stock_id,
                        customer_loc,
                        warehouse.pick_type_id,
                        "pull",
                    ),
                    self.Routing(
                        warehouse.wh_output_stock_loc_id,
                        customer_loc,
                        warehouse.out_type_id,
                        "push",
                    ),
                ],
                "pick_pack_ship": [
                    self.Routing(
                        warehouse.lot_stock_id,
                        customer_loc,
                        warehouse.pick_type_id,
                        "pull",
                    ),
                    self.Routing(
                        warehouse.wh_pack_stock_loc_id,
                        warehouse.wh_output_stock_loc_id,
                        warehouse.pack_type_id,
                        "push",
                    ),
                    self.Routing(
                        warehouse.wh_output_stock_loc_id,
                        customer_loc,
                        warehouse.out_type_id,
                        "push",
                    ),
                ],
            }
            for warehouse in self
        }

    def _get_receive_rules_dict(self):
        """Same as get_rules_dict's reception steps, but without the initial
        pull rule from the supplier: the receive route is meant to only push
        internally, not to pull on its own. Used together with
        _get_receive_routes_values().
        """
        return {
            "one_step": [],
            "two_steps": [
                self.Routing(
                    self.wh_input_stock_loc_id,
                    self.lot_stock_id,
                    self.store_type_id,
                    "push",
                )
            ],
            "three_steps": [
                self.Routing(
                    self.wh_input_stock_loc_id,
                    self.wh_qc_stock_loc_id,
                    self.qc_type_id,
                    "push",
                ),
                self.Routing(
                    self.wh_qc_stock_loc_id,
                    self.lot_stock_id,
                    self.store_type_id,
                    "push",
                ),
            ],
        }

    def _get_inter_warehouse_route_values(self, supplier_warehouse):
        return {
            "name": _(
                "%(warehouse)s: Supply Product from %(supplier)s",
                warehouse=self.name,
                supplier=supplier_warehouse.name,
            ),
            "warehouse_selectable": True,
            "product_selectable": True,
            "product_categ_selectable": True,
            "supplied_wh_id": self.id,
            "supplier_wh_id": supplier_warehouse.id,
            "company_id": (self.company_id & supplier_warehouse.company_id).id,
        }

    # Pull / Push tools
    # ------------------------------------------------------------

    def _get_rule_values(self, route_values, values=None, name_suffix=""):
        first_rule = True
        rules_list = []
        for routing in route_values:
            route_rule_values = {
                "name": self._format_rulename(
                    routing.from_loc, routing.dest_loc, name_suffix
                ),
                "location_src_id": routing.from_loc.id,
                "location_dest_id": routing.dest_loc.id,
                "action": routing.action,
                "auto": "manual",
                "picking_type_id": routing.picking_type.id,
                "procure_method": "make_to_stock" if first_rule else "make_to_order",
                "warehouse_id": self.id,
                "company_id": self.company_id.id,
            }
            route_rule_values.update(values or {})
            rules_list.append(route_rule_values)
            first_rule = False
        if values and values.get("propagate_cancel") and rules_list:
            # Don't propagate cancellation past the last rule of the chain, e.g.
            # for Input -> QC -> Stock -> Customer, cancelling Input -> QC should
            # cancel QC -> Stock but not Stock -> Customer.
            rules_list[-1]["propagate_cancel"] = False
        return rules_list

    def _get_supply_pull_rules_values(self, route_values, values=None):
        # `values` is documented optional (default None); copy defensively so the
        # default doesn't raise on `.update(None)`.
        pull_values = dict(values or {})
        pull_values["active"] = True
        rules_list = self._get_rule_values(route_values, values=pull_values)
        for pull_rules in rules_list:
            # The first leg of the resupply route (sourced from stock) is MTS;
            # every downstream leg pulls from the previous one, hence MTO.
            pull_rules["procure_method"] = (
                "make_to_order"
                if self.lot_stock_id.id != pull_rules["location_src_id"]
                else "make_to_stock"
            )
        return rules_list

    def _update_reception_delivery_resupply(self, reception_new, delivery_new):
        """Check if we need to change something to resupply warehouses and associated MTO rules"""
        for warehouse in self:
            _input_loc, output_loc = warehouse._get_input_output_locations(
                reception_new, delivery_new
            )
            if (
                delivery_new
                and warehouse.delivery_steps != delivery_new
                and (
                    warehouse.delivery_steps == "ship_only"
                    or delivery_new == "ship_only"
                )
            ):
                change_to_multiple = warehouse.delivery_steps == "ship_only"
                warehouse._check_delivery_resupply(output_loc, change_to_multiple)

    def _check_delivery_resupply(self, new_location, change_to_multiple):
        """Update the resupply routes/rules of warehouses supplied by this one
        to follow a change between single-step ('ship_only') and multi-step
        delivery: repoint the rule feeding the transit location, and
        add/remove the extra Output-from-Stock leg and its MTO rule.
        """
        Rule = self.env["stock.rule"]
        routes = self.env["stock.route"].search([("supplier_wh_id", "=", self.id)])
        rules = Rule.search(
            [
                ("route_id", "in", routes.ids),
                ("action", "!=", "push"),
                ("location_dest_id.usage", "=", "transit"),
            ]
        )
        rules.write(
            {
                "location_src_id": new_location.id,
                "procure_method": "make_to_order"
                if change_to_multiple
                else "make_to_stock",
            }
        )
        if not change_to_multiple:
            # Remove the extra rule to resupply Output from Stock
            rules_to_archive = Rule.search(
                [
                    ("route_id", "in", routes.ids),
                    ("action", "!=", "push"),
                    ("location_dest_id", "=", self.wh_output_stock_loc_id.id),
                    ("picking_type_id", "=", self.pick_type_id.id),
                ]
            )
            rules_to_archive.active = False

            # If single delivery we should create the necessary MTO rules for the resupply
            routings = [
                self.Routing(self.lot_stock_id, location, self.out_type_id, "pull")
                for location in rules.location_dest_id
            ]
            mto_vals = self._get_global_route_rules_values().get("mto_pull_id")
            # Skip when the MTO route can't be resolved (see create_resupply_routes).
            if mto_vals:
                values = mto_vals["create_values"]
                mto_rule_vals = self._get_rule_values(
                    routings, values, name_suffix="MTO"
                )
                Rule.create(mto_rule_vals)
        else:
            # Add the missing rules to resupply Output from Stock
            rules_to_unarchive = Rule.with_context(active_test=False).search(
                [
                    ("route_id", "in", routes.ids),
                    ("action", "!=", "push"),
                    ("location_dest_id", "=", self.wh_output_stock_loc_id.id),
                    ("picking_type_id", "=", self.pick_type_id.id),
                ]
            )
            rules_to_unarchive.active = True
            found_routes = rules_to_unarchive.route_id

            missing_rule_vals = []
            for route in routes - found_routes:
                missing_rule_vals += self._get_supply_pull_rules_values(
                    [
                        self.Routing(
                            self.lot_stock_id, new_location, self.pick_type_id, "pull"
                        )
                    ],
                    values={"route_id": route.id},
                )
            Rule.create(missing_rule_vals)

            # Deactivate the now-unneeded MTO rules from stock to transit, otherwise
            # they risk being used since resupply is no longer single-step.
            Rule.search(
                [
                    (
                        "route_id",
                        "=",
                        self._find_or_create_global_route(
                            "stock.route_warehouse0_mto",
                            _("Replenish on Order (MTO)"),
                            create=False,
                        ).id,
                    ),
                    ("location_dest_id.usage", "=", "transit"),
                    ("action", "!=", "push"),
                    ("location_src_id", "=", self.lot_stock_id.id),
                ]
            ).write({"active": False})

    def _update_name_and_code(self, new_name=False, new_code=False):
        if new_code:
            self.mapped("lot_stock_id").mapped("location_id").write({"name": new_code})
        if new_name:
            # Routes are named "<warehouse name>: <label>" (see _format_routename),
            # so keep them in sync by swapping just the leading prefix. The old
            # `name.replace(old, new, 1)` could match the wrong occurrence
            # mid-string and leave the label untouched.
            #
            # Rules are intentionally NOT renamed: _format_rulename builds their
            # names from the warehouse *code*, not its name, so a name change
            # never affects a rule name — the old per-rule and mto_pull_id
            # `.replace(warehouse.name, ...)` calls matched nothing (dead code).
            for warehouse in self:
                old_prefix = "%s: " % warehouse.name
                new_prefix = "%s: " % new_name
                for route in warehouse.route_ids:
                    if route.name and route.name.startswith(old_prefix):
                        route.name = new_prefix + route.name[len(old_prefix) :]
        # `ir.sequence` write access is limited to the system user.
        is_manager = self.env.user.has_group("stock.group_stock_manager")
        for warehouse in self:
            sequence_data = warehouse._get_sequence_values(name=new_name, code=new_code)
            wh = warehouse.sudo() if is_manager else warehouse
            # Data-driven so module-added picking types (mrp's pbm/sam/manu, pos,
            # repair, subcontracting, ...), whose keys `_get_sequence_values` also
            # returns, get their sequence renamed too — not just the base eight.
            # Keys are warehouse picking-type field names.
            for field_name, seq_vals in sequence_data.items():
                sequence = wh[field_name].sequence_id
                if sequence:
                    sequence.write(seq_vals)

    def _update_location_reception(self, new_reception_step):
        self.mapped("wh_qc_stock_loc_id").write(
            {"active": new_reception_step == "three_steps"}
        )
        self.mapped("wh_input_stock_loc_id").write(
            {"active": new_reception_step != "one_step"}
        )

    def _update_location_delivery(self, new_delivery_step):
        self.mapped("wh_pack_stock_loc_id").write(
            {"active": new_delivery_step == "pick_pack_ship"}
        )
        self.mapped("wh_output_stock_loc_id").write(
            {"active": new_delivery_step != "ship_only"}
        )

    # Misc
    # ------------------------------------------------------------

    def _normalized_code(self):
        """The warehouse code without spaces and upper-cased — the form used to
        build picking-type barcodes and location barcodes.
        """
        self.ensure_one()
        return (self.code or "").replace(" ", "").upper()

    def _get_picking_type_update_values(self):
        """Return values in order to update the existing picking type when the
        warehouse's delivery_steps or reception_steps are modify.
        """
        input_loc, output_loc = self._get_input_output_locations(
            self.reception_steps, self.delivery_steps
        )
        values = {
            "in_type_id": {
                "default_location_dest_id": input_loc.id,
            },
            "out_type_id": {
                "default_location_src_id": output_loc.id,
            },
            "pick_type_id": {
                "active": self.delivery_steps != "ship_only" and self.active,
                "default_location_dest_id": (
                    output_loc.id
                    if self.delivery_steps == "pick_ship"
                    else self.wh_pack_stock_loc_id.id
                ),
            },
            "pack_type_id": {
                "active": self.delivery_steps == "pick_pack_ship" and self.active,
                "default_location_dest_id": output_loc.id,
            },
            "qc_type_id": {
                "active": self.reception_steps == "three_steps" and self.active,
            },
            "store_type_id": {
                "active": self.reception_steps != "one_step" and self.active,
                "default_location_src_id": (
                    input_loc.id
                    if self.reception_steps == "two_steps"
                    else self.wh_qc_stock_loc_id.id
                ),
            },
            "int_type_id": {},
            "xdock_type_id": {
                "active": self.reception_steps != "one_step"
                and self.delivery_steps != "ship_only"
                and self.active,
            },
        }
        # Barcode suffix == the picking type's sequence_code (WAREHOUSE_PICKING_
        # TYPE_CODES), so it can't drift from the create/sequence values. Also
        # resolves _normalized_code once instead of per type.
        code = self._normalized_code()
        for field, seq_code in WAREHOUSE_PICKING_TYPE_CODES.items():
            values[field]["barcode"] = code + seq_code
        return values

    def _get_picking_type_create_values(self, max_sequence):
        """Return the creation values for a new warehouse's picking types. All
        picking types are created together, but activated/archived based on
        the delivery_steps/reception_steps in effect.
        """
        # Only the output location is used below; input_loc is discarded.
        _input_loc, output_loc = self._get_input_output_locations(
            self.reception_steps, self.delivery_steps
        )
        values = {
            "in_type_id": {
                "name": _("Receipts"),
                "code": "incoming",
                "use_existing_lots": False,
                "company_id": self.company_id.id,
            },
            "out_type_id": {
                "name": _("Delivery Orders"),
                "code": "outgoing",
                "use_create_lots": False,
                "print_label": True,
                "company_id": self.company_id.id,
            },
            "pack_type_id": {
                "name": _("Pack"),
                "code": "internal",
                "use_create_lots": False,
                "use_existing_lots": True,
                "default_location_src_id": self.wh_pack_stock_loc_id.id,
                "default_location_dest_id": output_loc.id,
                "company_id": self.company_id.id,
            },
            "pick_type_id": {
                "name": _("Pick"),
                "code": "internal",
                "use_create_lots": False,
                "use_existing_lots": True,
                "default_location_src_id": self.lot_stock_id.id,
                "company_id": self.company_id.id,
            },
            "qc_type_id": {
                "name": _("Quality Control"),
                "code": "internal",
                "use_create_lots": False,
                "use_existing_lots": True,
                "default_location_src_id": self.wh_input_stock_loc_id.id,
                "default_location_dest_id": self.wh_qc_stock_loc_id.id,
                "company_id": self.company_id.id,
            },
            "store_type_id": {
                "name": _("Storage"),
                "code": "internal",
                "use_create_lots": False,
                "use_existing_lots": True,
                "default_location_dest_id": self.lot_stock_id.id,
                "company_id": self.company_id.id,
            },
            "int_type_id": {
                "name": _("Internal Transfers"),
                "code": "internal",
                "use_create_lots": False,
                "use_existing_lots": True,
                "default_location_src_id": self.lot_stock_id.id,
                "default_location_dest_id": self.lot_stock_id.id,
                "active": self.env.user.has_group("stock.group_stock_multi_locations"),
                "company_id": self.company_id.id,
            },
            "xdock_type_id": {
                "name": _("Cross Dock"),
                "code": "internal",
                "use_create_lots": False,
                "use_existing_lots": True,
                "default_location_src_id": self.wh_input_stock_loc_id.id,
                "default_location_dest_id": self.wh_output_stock_loc_id.id,
                "company_id": self.company_id.id,
            },
        }
        # sequence_code and each type's creation-sequence offset both come from
        # WAREHOUSE_PICKING_TYPE_CODES (its order == the offset), so adding a base
        # picking type is one entry there rather than a hand-picked "+N" here.
        for offset, (field, seq_code) in enumerate(
            WAREHOUSE_PICKING_TYPE_CODES.items(), start=1
        ):
            values[field]["sequence_code"] = seq_code
            values[field]["sequence"] = max_sequence + offset
        return values, max_sequence + len(WAREHOUSE_PICKING_TYPE_CODES) + 1

    def _get_sequence_values(self, name=False, code=False):
        """Each picking type is created with a sequence. This method returns
        the sequence values associated to each picking type.
        """
        name = name or self.name
        code = code or self.code
        values = {
            "in_type_id": {"name": _("%(name)s Sequence in", name=name)},
            "out_type_id": {"name": _("%(name)s Sequence out", name=name)},
            "pack_type_id": {"name": _("%(name)s Sequence packing", name=name)},
            "pick_type_id": {"name": _("%(name)s Sequence picking", name=name)},
            "qc_type_id": {"name": _("%(name)s Sequence quality control", name=name)},
            "store_type_id": {"name": _("%(name)s Sequence storage", name=name)},
            "int_type_id": {"name": _("%(name)s Sequence internal", name=name)},
            "xdock_type_id": {"name": _("%(name)s Sequence cross dock", name=name)},
        }
        # prefix/padding/company are identical scaffolding across every type; the
        # prefix's code segment falls back to the shared WAREHOUSE_PICKING_TYPE_
        # CODES value when the picking type has no sequence_code yet.
        for field, seq_code in WAREHOUSE_PICKING_TYPE_CODES.items():
            values[field].update(
                {
                    "prefix": code
                    + "/"
                    + (self[field].sequence_code or seq_code)
                    + "/",
                    "padding": 5,
                    "company_id": self.company_id.id,
                }
            )
        return values

    def _format_rulename(self, from_loc, dest_loc, suffix):
        rulename = "%s: %s" % (self.code, from_loc.name)
        if dest_loc:
            rulename += " → %s" % (dest_loc.name)
        if suffix:
            rulename += " (" + suffix + ")"
        return rulename

    def _format_routename(self, name=None, route_type=None):
        if route_type:
            name = self._get_route_name(route_type)
        return "%s: %s" % (self.name, name)

    def _get_all_routes(self):
        routes = self.mapped("route_ids") | self.mapped("mto_pull_id").mapped(
            "route_id"
        )
        routes |= (
            self.env["stock.route"]
            .with_context(active_test=False)
            .search([("supplied_wh_id", "in", self.ids)])
        )
        return routes

    def action_view_all_routes(self):
        routes = self._get_all_routes()
        return {
            "name": _("Warehouse's Routes"),
            "domain": [("id", "in", routes.ids)],
            "res_model": "stock.route",
            "type": "ir.actions.act_window",
            "view_id": False,
            "view_mode": "list,form",
            "limit": 20,
            "context": dict(
                self.env.context,
                default_warehouse_selectable=True,
                default_warehouse_ids=self.ids,
            ),
        }

    def get_current_warehouses(self):
        return self.env["stock.warehouse"].search_read(
            [("company_id", "in", self.env.companies.ids)],
            fields=["id", "name", "code"],
        )
