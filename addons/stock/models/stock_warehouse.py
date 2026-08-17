import logging
import typing
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.tools import ormcache
from odoo.tools.translate import LazyTranslate, _

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)


class Routing(typing.NamedTuple):
    """One leg of a warehouse route: take from `from_loc`, put in `dest_loc`,
    through `picking_type`, by a rule of kind `action` ("pull" / "push" / ...).

    Module-level so the field types are declared once and read by the type
    checker; `StockWarehouse.Routing` still aliases it, since every call site
    (and every override in a sibling repo) builds one via `self.Routing(...)`.
    """

    from_loc: models.Model
    dest_loc: models.Model
    picking_type: models.Model
    action: str


ROUTE_NAMES = {
    "one_step": _lt("Receive in 1 step (stock)"),
    "two_steps": _lt("Receive in 2 steps (input + stock)"),
    "three_steps": _lt("Receive in 3 steps (input + quality + stock)"),
    "ship_only": _lt("Deliver in 1 step (ship)"),
    "pick_ship": _lt("Deliver in 2 steps (pick + ship)"),
    "pick_pack_ship": _lt("Deliver in 3 steps (pick + pack + ship)"),
}

PARTNER_LOCATION_XML_IDS = {
    "customer": "stock.stock_location_customers",
    "supplier": "stock.stock_location_suppliers",
}

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

    Routing = Routing

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
        copy=False,
        required=True,
        check_company=True,
        domain="[('usage', '=', 'view'), ('company_id', '=', company_id)]",
        index=True,
    )
    lot_stock_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location Stock",
        copy=False,
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
        copy=False,
        check_company=True,
    )
    wh_qc_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Quality Control Location",
        copy=False,
        check_company=True,
    )
    wh_output_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Output Location",
        copy=False,
        check_company=True,
    )
    wh_pack_stock_loc_id = fields.Many2one(
        comodel_name="stock.location",
        string="Packing Location",
        copy=False,
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

    _warehouse_name_uniq = models.Constraint(
        "unique(name, company_id)",
        "The name of the warehouse must be unique per company!",
    )
    _warehouse_code_uniq = models.Constraint(
        "unique(code, company_id)",
        "The short name of the warehouse must be unique per company!",
    )

    @api.constrains("resupply_wh_ids")
    def _check_resupply_wh_ids(self):
        """A warehouse cannot resupply itself.

        The form view already excludes it by domain, but import, RPC and code do
        not go through the view, and the resulting route is not inert: a
        procurement at that warehouse's own stock resolves through it into a
        delivery order to transit plus a receipt back, moving real quantities
        for no net effect.
        """
        for warehouse in self:
            if warehouse in warehouse.resupply_wh_ids:
                raise ValidationError(
                    _(
                        "Warehouse %s cannot be resupplied by itself.",
                        warehouse.display_name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        taken_names = defaultdict(set)
        taken_codes = defaultdict(set)
        for vals in vals_list:
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
            if vals.get("name"):
                taken_names[company.id].add(vals["name"])
            if vals.get("code"):
                taken_codes[company.id].add(vals["code"])
            if not vals.get("view_location_id"):
                loc_vals = {
                    "name": vals["code"],
                    "usage": "view",
                    "company_id": company.id,
                }
                vals["view_location_id"] = (
                    self.env["stock.location"].create(loc_vals).id
                )
            sub_locations = {
                field: values
                for field, values in self.browse()
                .with_context(stock_warehouse_probe=True)
                ._get_locations_values(vals)
                .items()
                if not vals.get(field)
            }
            self._resolve_barcodes(list(sub_locations.values()), company.id)
            for values in sub_locations.values():
                values["location_id"] = vals["view_location_id"]
                values["company_id"] = company.id
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
            warehouse.write(new_vals)
            warehouse._create_or_update_route()
            warehouse._create_or_update_global_routes_rules()

            warehouse.create_resupply_routes(warehouse.resupply_wh_ids)

            if vals.get("partner_id"):
                self._update_partner_data(vals["partner_id"], vals.get("company_id"))

            self.env["stock.location"].browse(
                vals.get("view_location_id")
            )._recompute_descendants_warehouse()

        self._check_multiwarehouse_group()

        return warehouses

    def write(self, vals):
        """Keep the warehouse's locations, picking types, routes and rules in
        step with the fields being written.

        The work splits cleanly around ``super()``: what has to observe the
        *old* values (snapshots, renames driven by the previous name/code) runs
        before, what rebuilds from the *new* ones runs after. ``_pre_write_sync``
        hands the second half everything the first half could still see.
        """
        self._check_company_unchanged(vals)
        warehouses = self.with_context(active_test=False)
        before = warehouses._pre_write_sync(vals)

        res = super().write(vals)

        warehouses._post_write_refresh(vals, before)
        return res

    def _check_company_unchanged(self, vals):
        if "company_id" not in vals:
            return
        for warehouse in self:
            if warehouse.company_id.id != vals["company_id"]:
                raise UserError(
                    _(
                        "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                    )
                )

    def _pre_write_sync(self, vals):
        """Everything ``write`` must do while the records still hold their old
        values, plus the snapshots ``_post_write_refresh`` needs afterwards.
        """
        warehouses = self
        warehouses._create_missing_locations(vals)

        if vals.get("reception_steps"):
            warehouses._update_location_reception(vals["reception_steps"])

        if vals.get("delivery_steps"):
            warehouses._update_location_delivery(vals["delivery_steps"])

        if vals.get("reception_steps") or vals.get("delivery_steps"):
            warehouses._update_reception_delivery_resupply(
                vals.get("reception_steps"), vals.get("delivery_steps")
            )

        old_resupply_whs = {}
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

        toggling = (
            warehouses.filtered(lambda w: w.active != bool(vals["active"]))
            if "active" in vals
            else warehouses.browse()
        )

        view_locations = self.env["stock.location"].browse()
        if "view_location_id" in vals:
            view_locations = warehouses.view_location_id | self.env[
                "stock.location"
            ].browse(vals["view_location_id"])

        return {
            "toggling": toggling,
            "view_locations": view_locations,
            "old_resupply_whs": old_resupply_whs,
        }

    def _post_write_refresh(self, vals, before):
        """Rebuild what the write invalidated, from the *new* field values.

        ``before`` is ``_pre_write_sync``'s snapshot: the records that actually
        changed ``active``, the view locations whose subtree must be recomputed,
        and the pre-write ``resupply_wh_ids``.
        """
        warehouses = self
        view_locations = before["view_locations"]
        if view_locations:
            view_locations.exists()._recompute_descendants_warehouse()

        if warehouses:
            route_depends, global_depends, global_rule_keys = warehouses[
                :1
            ]._get_route_trigger_fields()
        else:
            route_depends = global_depends = global_rule_keys = frozenset()
        changed = vals.keys()
        refresh_picking_types = "code" in changed or not route_depends.isdisjoint(
            changed
        )
        refresh_routes = not route_depends.isdisjoint(changed)
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

            if warehouse in before["toggling"]:
                warehouse._toggle_active(vals["active"], route_depends | global_depends)

        for warehouse in warehouses:
            if warehouse.id in before["old_resupply_whs"]:
                warehouse._sync_resupply_routes(
                    before["old_resupply_whs"][warehouse.id]
                )

        if "active" in vals:
            self._check_multiwarehouse_group()

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

        Runs under the ``stock_warehouse_probe`` context so ``_valid_barcode``
        does not emit its collision warning: only the dict keys are read here,
        no location is about to be created.
        """
        return tuple(
            self.with_context(stock_warehouse_probe=True)._get_locations_values({})
        )

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

        The generation runs under the ``stock_warehouse_probe`` context: only
        the dict keys and ``depends`` are read here, so the probe suppresses the
        side effects of the real generation path — ``_find_or_create_global_route``
        must not create a route, and the base MTO resolution must not raise —
        while unmodified module overrides keep working unchanged.

        Structural, hence cached — a module override can still ``raise`` for
        this warehouse's company (e.g. mrp's production-location lookup). The
        raise propagates *before* ormcache stores anything, so a misconfigured
        warehouse never poisons this cache for its healthy siblings: the caller
        retries on the other warehouses, and the next successful call caches
        the real set.
        """
        global_values = self.with_context(
            stock_warehouse_probe=True
        )._generate_global_route_rules_values()
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

        The global part is computed under a side-effect-free probe (see
        ``_get_global_trigger_fields``), but a module override may still raise
        for a given warehouse's company (e.g. mrp's production-location
        lookup). The sets are structural — identical for every warehouse — so
        retry the cached computation through the other warehouses before
        falling back. The last-resort fallback is over-inclusive on the rule
        keys (every ``stock.rule`` Many2one on the warehouse is treated as a
        trigger); the ``depends`` fall back to the base set until the next
        successful computation caches the real one.
        """
        route_depends = self._get_route_depend_fields()
        probe = self.sudo().with_context(active_test=False)
        for warehouse in probe:
            try:
                global_depends, global_rule_keys = (
                    warehouse._get_global_trigger_fields()
                )
                return route_depends, global_depends, global_rule_keys
            except UserError:
                continue
        for warehouse in probe.search([("id", "not in", probe.ids)]):
            try:
                global_depends, global_rule_keys = (
                    warehouse._get_global_trigger_fields()
                )
                return route_depends, global_depends, global_rule_keys
            except UserError:
                continue
        _logger.warning(
            "Could not resolve global route rules on any warehouse while "
            "computing route trigger fields; falling back to structural "
            "defaults.",
        )
        global_rule_keys = frozenset(
            name
            for name, field in self._fields.items()
            if field.type == "many2one" and field.comodel_name == "stock.rule"
        )
        return route_depends, frozenset({"delivery_steps"}), global_rule_keys

    def _default_name(self):
        return self._generate_default_name(self.env.company)

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

    def _toggle_active(self, active, reactivate_depends):
        """(Un)archive the warehouse together with its picking types, locations,
        routes and rules to match ``active``.

        Refuses to *archive* while there are ongoing operations, or when a picking
        type outside this warehouse still points at one of its locations. On
        reactivation, ``reactivate_depends`` (the route/global trigger fields) is
        re-written on the warehouse so ``write`` rebuilds its dependent records.
        """
        self.ensure_one()
        PickingType = self.env["stock.picking.type"]
        picking_types = PickingType.with_context(active_test=False).search(
            [("warehouse_id", "=", self.id)]
        )
        if not active:
            self._check_archivable(picking_types)
        picking_types.write({"active": active})
        self.view_location_id.write({"active": active})

        rules = (
            self.env["stock.rule"]
            .with_context(active_test=False)
            .search([("warehouse_id", "=", self.id)])
        )
        self.route_ids.filtered(lambda r: len(r.warehouse_ids) == 1).write(
            {"active": active}
        )
        rules.write({"active": active})

        if active:
            values = {
                "resupply_route_ids": [
                    (4, route.id) for route in self.resupply_route_ids
                ]
            }
            for depend in reactivate_depends:
                values[depend] = self[depend]
            self.write(values)
            self._align_resupply_rule_activity()

    def _check_archivable(self, picking_types):
        """Raise unless this warehouse can be archived: no ongoing operation on
        ``picking_types``, and no picking type outside it defaulting to one of
        its locations (which archiving would leave dangling).
        """
        self.ensure_one()
        open_moves_by_type = self.env["stock.move"]._read_group(
            [
                ("picking_type_id", "in", picking_types.ids),
                ("state", "not in", ("done", "cancel")),
            ],
            ["picking_type_id"],
        )
        if open_moves_by_type:
            raise UserError(
                _(
                    "You still have ongoing operations for operation types %(operations)s in warehouse %(warehouse)s",
                    operations=[
                        picking_type.name for (picking_type,) in open_moves_by_type
                    ],
                    warehouse=self.name,
                )
            )
        locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("location_id", "child_of", self.view_location_id.id)])
        )
        picking_type_using_locations = self.env["stock.picking.type"].search(
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
        if not self.env.registry.ready:
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
        """Keep ``group_stock_multi_warehouses`` in step with the largest number
        of active warehouses any company has.

        Runs entirely under ``sudo()``. Implying a group on ``base.group_user``
        and flipping the Storage Locations setting are system-level consequences
        of an operation the ACL already grants: ``stock.group_stock_manager``
        holds full CRUD on ``stock.warehouse`` and the Warehouses menu is gated
        on that same group. Unsudoed, a plain stock manager creating their
        company's *second* warehouse died with ``AccessError`` on
        ``res.config.settings`` (or, when Storage Locations was already on, on
        ``res.groups``) — reachable out of the box, with no group tampering.
        ``sudo()`` raises ``su``, not ``uid``, so
        ``res.config.settings.set_values`` still sees the real user for its own
        manager check.
        """
        self = self.sudo()
        cnt_by_company = self.env["stock.warehouse"]._read_group(
            [("active", "=", True)], ["company_id"], aggregates=["__count"]
        )
        max_count = max((count for _company, count in cnt_by_company), default=0)
        group_user = self.env.ref("base.group_user")
        group_stock_multi_warehouses = self.env.ref(
            "stock.group_stock_multi_warehouses"
        )
        group_stock_multi_locations = self.env.ref("stock.group_stock_multi_locations")
        if max_count <= 1 and group_stock_multi_warehouses in group_user.implied_ids:
            group_user.write({"implied_ids": [(3, group_stock_multi_warehouses.id)]})
            group_stock_multi_warehouses.write(
                {"user_ids": [(3, user.id) for user in group_user.all_user_ids]}
            )
        if max_count > 1 and group_stock_multi_warehouses not in group_user.implied_ids:
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

        max_sequence = (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search_read(
                [("sequence", "!=", False)],
                ["sequence"],
                limit=1,
                order="sequence desc",
            )
        )
        max_sequence = (max_sequence and max_sequence[0]["sequence"]) or 0

        data = self._get_picking_type_update_values()
        create_data = self._get_picking_type_create_values()
        codes = self._get_picking_type_codes()
        self._check_picking_type_registry(data, create_data, sequence_data, codes)
        for offset, (field, seq_code) in enumerate(codes.items(), start=1):
            create_data[field]["sequence_code"] = seq_code
            create_data[field]["sequence"] = max_sequence + offset

        to_update = [field for field in data if self[field]]
        to_create = [field for field in data if not self[field]]

        for field in to_update:
            self[field].sudo().sequence_id.write({"company_id": self.company_id.id})
            self[field].write(data[field])

        if to_create:
            clashing_names = {
                name
                for (name,) in IrSequenceSudo._read_group(
                    [
                        ("name", "in", [sequence_data[f]["name"] for f in to_create]),
                        (
                            "company_id",
                            "in",
                            list({sequence_data[f]["company_id"] for f in to_create}),
                        ),
                    ],
                    ["name"],
                )
            }
            sequences = IrSequenceSudo.create(
                [sequence_data[field] for field in to_create]
            )
            picking_type_vals = []
            for field, sequence in zip(to_create, sequences, strict=True):
                if sequence_data[field]["name"] in clashing_names:
                    sequence.name = _(
                        "%(name)s (copy)(%(id)s)",
                        name=sequence.name,
                        id=str(sequence.id),
                    )
                values = dict(data[field], **create_data[field])
                values.update(
                    warehouse_id=self.id, color=color, sequence_id=sequence.id
                )
                picking_type_vals.append(values)
            picking_types = PickingType.create(picking_type_vals)
            for field, picking_type in zip(to_create, picking_types, strict=True):
                warehouse_data[field] = picking_type.id

        if "out_type_id" in warehouse_data:
            PickingType.browse(warehouse_data["out_type_id"]).write(
                {"return_picking_type_id": warehouse_data.get("in_type_id", False)}
            )
        if "in_type_id" in warehouse_data:
            PickingType.browse(warehouse_data["in_type_id"]).write(
                {"return_picking_type_id": warehouse_data.get("out_type_id", False)}
            )
        return warehouse_data

    @api.model
    def _check_picking_type_registry(
        self, update_data, create_data, sequence_data, codes
    ):
        """Fail loudly when the four picking-type mappings disagree on their keys.

        ``_create_or_update_sequences_and_picking_types`` indexes ``create_data``
        and ``sequence_data`` by the keys of ``update_data``, and allocates
        sequences by the keys of ``codes``. A module extending only some of them
        used to be either silently ignored (create-only) or a bare ``KeyError``
        deep inside the create loop (update-only), neither of which names the
        module at fault. The four are one declaration; say so.
        """
        expected = set(codes)
        for label, mapping in (
            ("_get_picking_type_update_values", update_data),
            ("_get_picking_type_create_values", create_data),
            ("_get_sequence_values", sequence_data),
        ):
            missing = expected - set(mapping)
            extra = set(mapping) - expected
            if missing or extra:
                raise ValueError(
                    "stock.warehouse picking-type declarations disagree: "
                    "%s is missing %s and declares unregistered %s. Every "
                    "picking type must appear in _get_picking_type_codes, "
                    "_get_picking_type_create_values, "
                    "_get_picking_type_update_values and _get_sequence_values."
                    % (label, sorted(missing) or "nothing", sorted(extra) or "nothing")
                )

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
                        ("name", "=", route_name),
                        ("company_id", "in", [False, company.id]),
                    ],
                    order="company_id",
                    limit=1,
                )
            )
        if not route:
            if raise_if_not_found:
                raise UserError(_("Can't find any generic route %s.", route_name))
            if (
                data_route
                and create
                and not self.env.context.get("stock_warehouse_probe")
            ):
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
        return {
            k: v
            for k, v in vals.items()
            if v.get("create_values", {}).get("route_id", True)
            and v.get("update_values", {}).get("route_id", True)
        }

    def _generate_global_route_rules_values(self):
        delivery_rules = self.get_rules_dict()[self.id][self.delivery_steps]
        rule = next(
            (r for r in delivery_rules if r.from_loc == self.lot_stock_id), None
        )
        if (
            not rule
            and delivery_rules
            and self.env.context.get("stock_warehouse_probe")
        ):
            rule = delivery_rules[0]
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
        if to_create:
            Rule.create(to_create)

    def _get_location_step_fields(self):
        """Warehouse fields ``_get_locations_values`` resolves its sub-locations'
        ``active`` flags (and company) from. A module adding a step-dependent
        sub-location extends this alongside ``_get_locations_values``.
        """
        return ["reception_steps", "delivery_steps", "company_id"]

    def _get_location_step_values(self, vals):
        """Resolve ``_get_location_step_fields`` for ``_get_locations_values``:
        whatever ``vals`` carries, else the value **this warehouse** already has,
        else the field default.

        The record has to win over the default. ``_create_missing_locations``
        calls the values builder bound to an existing warehouse with only the
        current write's ``vals``; resolving straight from ``default_get`` rebuilt
        a two-steps warehouse's Input location with the ``one_step`` default —
        that is, archived — and nothing downstream repairs it, because
        ``_update_location_reception`` only runs when ``reception_steps`` is in
        ``vals``.
        """
        field_names = self._get_location_step_fields()
        values = {name: vals[name] for name in field_names if name in vals}
        missing = [name for name in field_names if name not in values]
        if not missing:
            return values
        record = self if len(self) == 1 else self.browse()
        defaults = {} if record else self.default_get(missing)
        for name in missing:
            if not record:
                values[name] = defaults[name]
                continue
            value = record[name]
            values[name] = value.id if isinstance(value, models.BaseModel) else value
        return values

    def _get_locations_values(self, vals, code=False):
        """Return create/update values for the warehouse's sub-locations
        (Stock, Input, Quality Control, Output, Packing Zone), activating each
        one depending on the reception/delivery steps.
        """
        def_values = self._get_location_step_values(vals)
        reception_steps = def_values["reception_steps"]
        delivery_steps = def_values["delivery_steps"]
        code = vals.get("code") or code or ""
        code = code.replace(" ", "").upper()
        company_id = def_values["company_id"]
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
        """``barcode`` if free in ``company_id``, else ``False`` with a warning.

        One query per call. Prefer ``_resolve_barcodes`` when several
        sub-locations are being built at once — under the
        ``stock_warehouse_probe`` context this returns the intended barcode
        unresolved, which is exactly what that batch path relies on.
        """
        if self.env.context.get("stock_warehouse_probe"):
            return barcode
        location = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search(
                [("barcode", "=", barcode), ("company_id", "=", company_id)], limit=1
            )
        )
        if location:
            _logger.warning(
                "Barcode %s is already used by location %s; the new warehouse "
                "location will be created without a barcode.",
                barcode,
                location.display_name,
            )
            return False
        return barcode

    @api.model
    def _resolve_barcodes(self, values_list, company_id):
        """Blank out, in one query, every barcode in ``values_list`` already used
        in ``company_id``, warning for each.

        ``stock.location`` declares ``unique(barcode, company_id)``, so a
        duplicate would abort the whole create. Callers build their values under
        ``stock_warehouse_probe`` (barcodes unresolved, no query) and settle the
        lot here, instead of paying one search per sub-location.
        """
        wanted = {values["barcode"] for values in values_list if values.get("barcode")}
        if not wanted:
            return
        taken = {
            row["barcode"]: row["complete_name"]
            for row in self.env["stock.location"]
            .with_context(active_test=False)
            .search_read(
                [("barcode", "in", list(wanted)), ("company_id", "=", company_id)],
                ["barcode", "complete_name"],
            )
        }
        for values in values_list:
            owner = taken.get(values.get("barcode"))
            if owner:
                _logger.warning(
                    "Barcode %s is already used by location %s; the new warehouse "
                    "location will be created without a barcode.",
                    values["barcode"],
                    owner,
                )
                values["barcode"] = False

    def _create_missing_locations(self, vals):
        """It could happen that the user delete a mandatory location or a
        module with new locations was installed after some warehouses creation.
        In this case, this function will create missing locations in order to
        avoid mistakes during picking types and rules creation.
        """
        location_fields = self._sub_location_field_names()
        for warehouse in self:
            if all(warehouse[field] or field in vals for field in location_fields):
                continue
            company_id = vals.get("company_id", warehouse.company_id.id)
            sub_locations = warehouse.with_context(
                stock_warehouse_probe=True
            )._get_locations_values(dict(vals, company_id=company_id), warehouse.code)
            missing = {
                field: values
                for field, values in sub_locations.items()
                if not warehouse[field] and field not in vals
            }
            if not missing:
                continue
            for values in missing.values():
                values["location_id"] = vals.get(
                    "view_location_id", warehouse.view_location_id.id
                )
                values["company_id"] = company_id
            warehouse._resolve_barcodes(list(missing.values()), company_id)
            locations = self.env["stock.location"].create(list(missing.values()))
            warehouse.write(dict(zip(missing, locations.ids, strict=True)))

    def create_resupply_routes(self, supplier_warehouses):
        self.ensure_one()
        Route = self.env["stock.route"]
        Rule = self.env["stock.rule"]

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
            output_to_transit = self.Routing(
                output_location, transit_location, supplier_wh.out_type_id, "pull"
            )
            if supplier_wh.delivery_steps == "ship_only":
                mto_vals = supplier_wh._get_global_route_rules_values().get(
                    "mto_pull_id"
                )
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
            Rule.create(pull_rules_list)

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
    def _get_partner_location(self, usage):
        """Return the ``customer`` or ``supplier`` partner location.

        The single place that answers "where do goods come from / go to" for a
        whole database. The xml-id first, since that is the record the data files
        ship; any location of that usage otherwise, because the xml-id can be
        gone while the location it named is still there; and a ``UserError``
        naming the missing side if neither turns one up.

        Callers must go through this rather than ``env.ref`` on the xml-id. A
        bare ref has no fallback and reports its absence as
        ``ValueError: External ID not found in the system``, raised wherever the
        caller happened to stand — which is how a database missing one record
        used to fail in the middle of ``stock.picking.type`` creation, three
        frames below anything that mentions locations.
        """
        location = self.env.ref(
            PARTNER_LOCATION_XML_IDS[usage], raise_if_not_found=False
        )
        if not location:
            location = self.env["stock.location"].search(
                [("usage", "=", usage)], limit=1
            )
        if location:
            return location
        if usage == "customer":
            raise UserError(_("Can't find any customer location."))
        raise UserError(_("Can't find any supplier location."))

    @api.model
    def _get_partner_locations(self):
        """The ``(customer, supplier)`` pair, for the callers that need both.

        Raises when *either* is missing — every one of them goes on to build
        rules from both, and a missing supplier used to yield rules with no
        source location instead of an error.
        """
        return (
            self._get_partner_location("customer"),
            self._get_partner_location("supplier"),
        )

    def _get_route_name(self, route_type):
        if route_type not in ROUTE_NAMES:
            raise UserError(
                _(
                    "No route name is declared for the routing configuration %s.",
                    route_type,
                )
            )
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

    @api.model
    def _format_resupply_routename(self, supplied_name, supplier_name):
        """The name of an inter-warehouse resupply route. Single source, shared
        with ``_update_route_names`` so a rename of either endpoint rebuilds it
        instead of patching a string it has to guess the shape of.
        """
        return _(
            "%(warehouse)s: Supply Product from %(supplier)s",
            warehouse=supplied_name,
            supplier=supplier_name,
        )

    def _get_inter_warehouse_route_values(self, supplier_warehouse):
        return {
            "name": self._format_resupply_routename(self.name, supplier_warehouse.name),
            "warehouse_selectable": True,
            "product_selectable": True,
            "product_categ_selectable": True,
            "supplied_wh_id": self.id,
            "supplier_wh_id": supplier_warehouse.id,
            "company_id": (self.company_id & supplier_warehouse.company_id).id,
        }

    def _get_rule_values(self, routings, values=None, name_suffix=""):
        """Build ``stock.rule`` create-values for each ``Routing`` leg.

        ``routings`` is a list of ``Routing`` tuples — not the
        ``_get_routes_values()`` mapping that ``route_values`` names everywhere
        else in this model.
        """
        first_rule = True
        rules_list = []
        for routing in routings:
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
            rules_list[-1]["propagate_cancel"] = False
        return rules_list

    def _get_supply_pull_rules_values(self, routings, values=None):
        pull_values = dict(values or {})
        pull_values["active"] = True
        rules_list = self._get_rule_values(routings, values=pull_values)
        for pull_rules in rules_list:
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
            rules_to_archive = Rule.search(
                [
                    ("route_id", "in", routes.ids),
                    ("action", "!=", "push"),
                    ("location_dest_id", "=", self.wh_output_stock_loc_id.id),
                    ("picking_type_id", "=", self.pick_type_id.id),
                ]
            )
            rules_to_archive.active = False

            routings = [
                self.Routing(self.lot_stock_id, location, self.out_type_id, "pull")
                for location in rules.location_dest_id
            ]
            mto_vals = self._get_global_route_rules_values().get("mto_pull_id")
            if mto_vals:
                values = mto_vals["create_values"]
                mto_rule_vals = self._get_rule_values(
                    routings, values, name_suffix="MTO"
                )
                Rule.create(mto_rule_vals)
        else:
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

    def _align_resupply_rule_activity(self):
        """Re-align the active flag of the step-dependent resupply legs with the
        current delivery configuration.

        Reactivating a warehouse unarchives every rule scoped to it, including
        the legs `_check_delivery_resupply` had archived as configuration state:
        the Stock -> Output pick leg only exists for multi-step delivery, the
        Stock -> Transit MTO rules only for single-step delivery. Without this
        pass, an archive/unarchive cycle of a supplier warehouse resurrects the
        variant that contradicts its current delivery steps.

        Only toggles ``active`` on existing rules — creation/repointing remains
        `_check_delivery_resupply`'s job when the steps actually change.
        """
        self.ensure_one()
        Rule = self.env["stock.rule"].with_context(active_test=False)
        routes = self.env["stock.route"].search([("supplier_wh_id", "=", self.id)])
        if not routes:
            return
        multi_step = self.delivery_steps != "ship_only"
        pick_legs = Rule.search(
            [
                ("route_id", "in", routes.ids),
                ("action", "!=", "push"),
                ("location_dest_id", "=", self.wh_output_stock_loc_id.id),
                ("picking_type_id", "=", self.pick_type_id.id),
            ]
        )
        pick_legs.write({"active": multi_step})
        mto_route = self._find_or_create_global_route(
            "stock.route_warehouse0_mto",
            _("Replenish on Order (MTO)"),
            create=False,
        )
        if mto_route:
            Rule.search(
                [
                    ("route_id", "=", mto_route.id),
                    ("action", "!=", "push"),
                    ("location_dest_id.usage", "=", "transit"),
                    ("location_src_id", "=", self.lot_stock_id.id),
                    ("warehouse_id", "=", self.id),
                ]
            ).write({"active": not multi_step})

    def _update_name_and_code(self, new_name=False, new_code=False):
        """Propagate a rename / recode to everything whose name was derived from
        the old one. Runs *before* ``super().write()``, so ``warehouse.name`` and
        ``warehouse.code`` still hold the old values here.

        The two identifiers feed disjoint sets of derived names, and both have to
        be followed:

        - ``name`` -> route names (``_format_routename``), including the resupply
          routes, which name *both* endpoints and are not in ``route_ids``;
        - ``code`` -> the view location, rule names (``_format_rulename``) and the
          picking-type sequences.
        """
        if new_code:
            self.view_location_id.write({"name": new_code})
            self._update_rule_names(new_code)
        if new_name:
            self._update_route_names(new_name)
        is_manager = self.env.user.has_group("stock.group_stock_manager")
        for warehouse in self:
            sequence_data = warehouse._get_sequence_values(name=new_name, code=new_code)
            wh = warehouse.sudo() if is_manager else warehouse
            for field_name, seq_vals in sequence_data.items():
                sequence = wh[field_name].sequence_id
                if sequence:
                    sequence.write(seq_vals)

    def _update_route_names(self, new_name):
        """Swap ``new_name`` into every route name built from this warehouse's
        name. Call before ``super().write()``, while ``warehouse.name`` is old.

        Two shapes, both from this model: ``"<warehouse>: <label>"``
        (``_format_routename``) for the warehouse's own selectable routes, and
        ``"<supplied>: Supply Product from <supplier>"`` for the resupply routes,
        which name a second warehouse and live in neither warehouse's
        ``route_ids``. The resupply names are rebuilt from
        ``_format_resupply_routename`` rather than patched, so the template stays
        in one place and a rename of *either* endpoint lands.
        """
        new_prefix = "%s: " % new_name
        for warehouse in self:
            old_prefix = "%s: " % warehouse.name
            for route in warehouse.route_ids:
                if route.name and route.name.startswith(old_prefix):
                    route.name = new_prefix + route.name[len(old_prefix) :]
        resupply_routes = (
            self.env["stock.route"]
            .with_context(active_test=False)
            .search(
                [
                    "|",
                    ("supplied_wh_id", "in", self.ids),
                    ("supplier_wh_id", "in", self.ids),
                ]
            )
        )
        for route in resupply_routes:
            supplied, supplier = route.supplied_wh_id, route.supplier_wh_id
            if not (supplied and supplier):
                continue
            route.name = self._format_resupply_routename(
                new_name if supplied in self else supplied.name,
                new_name if supplier in self else supplier.name,
            )

    def _update_rule_names(self, new_code):
        """Swap ``new_code`` into every rule name built from this warehouse's
        code. Call before ``super().write()``, while ``warehouse.code`` is old.

        ``_format_rulename`` names rules ``"<code>: <src> → <dest>"``, so a recode
        left every rule — reception, delivery, MTO, resupply legs and the rules
        module overrides add — naming the previous code. That name is not
        cosmetic: it feeds ``move.origin`` and the moves' own names.

        Refreshing the routes instead would not do it: ``_find_existing_rule_or_create``
        matches on routing identity and returns the existing rule untouched, so
        the rebuild is idempotent *including* the stale name. Archived rules are
        renamed too — they come back on unarchive.
        """
        rules = (
            self.env["stock.rule"]
            .with_context(active_test=False)
            .search([("warehouse_id", "in", self.ids)])
        )
        new_prefix = "%s: " % new_code
        old_prefixes = {warehouse.id: "%s: " % warehouse.code for warehouse in self}
        for rule in rules:
            old_prefix = old_prefixes.get(rule.warehouse_id.id)
            if old_prefix and rule.name and rule.name.startswith(old_prefix):
                rule.name = new_prefix + rule.name[len(old_prefix) :]

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

    def _get_picking_type_codes(self):
        """Ordered ``{warehouse field: sequence_code}`` covering every picking
        type a warehouse owns. A module adds its types by extending this once —
        the position in the mapping fixes the type's ``sequence``, its
        ``sequence_code``, its barcode suffix and its ``ir.sequence`` prefix
        segment.

        This replaces the ``_get_picking_type_create_values(max_sequence) ->
        (values, next_max_sequence)`` cursor every override had to thread. Three
        of the seven overrides in the tree got that wrong — ``mrp``, ``repair``
        and ``mrp_subcontracting`` all returned ``max_sequence + N`` from the
        value they were *given* rather than from the one ``super()`` handed
        back — so the types they added shared a ``sequence`` with base types
        (measured: ``PICK`` and ``POS`` both at 29) and the Operations overview
        ordered them arbitrarily. Nothing enforced the cursor and nothing
        reported it; position in an ordered mapping needs neither.
        """
        return dict(WAREHOUSE_PICKING_TYPE_CODES)

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
        code = self._normalized_code()
        for field, seq_code in WAREHOUSE_PICKING_TYPE_CODES.items():
            values[field]["barcode"] = code + seq_code
        return values

    def _get_picking_type_create_values(self):
        """Return the creation values for a new warehouse's picking types. All
        picking types are created together, but activated/archived based on
        the delivery_steps/reception_steps in effect.

        No ``sequence`` here: it is allocated by
        ``_create_or_update_sequences_and_picking_types`` from each type's
        position in ``_get_picking_type_codes`` (see that method for why the
        former ``max_sequence`` cursor is gone).
        """
        _input_loc, output_loc = self._get_input_output_locations(
            self.reception_steps, self.delivery_steps
        )
        return {
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
        if not name:
            raise ValueError("_format_routename needs either a name or a route_type")
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

    @api.model
    def get_current_warehouses(self):
        """Called over RPC by the stock search panels, which pass no arguments:
        this reads ``env.companies``, never ``self``.
        """
        return self.env["stock.warehouse"].search_read(
            [("company_id", "in", self.env.companies.ids)],
            fields=["id", "name", "code"],
        )
