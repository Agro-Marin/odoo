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
    from_loc: models.Model
    dest_loc: models.Model
    picking_type: models.Model
    action: str


class OwnedRecords(typing.NamedTuple):
    """What a warehouse takes with it when it is deleted, in unlink order."""

    picking_types: models.Model
    rules: models.Model
    routes: models.Model
    config: tuple
    view_location: models.Model


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

PARTNER_LOCATION_MISSING = {
    "customer": _lt("Can't find any customer location."),
    "supplier": _lt("Can't find any supplier location."),
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

    # FIELDS
    # ------

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

    # CONSTRAINTS
    # -----------

    _warehouse_name_uniq = models.Constraint(
        "unique(name, company_id)",
        "The name of the warehouse must be unique per company!",
    )

    _warehouse_code_uniq = models.Constraint(
        "unique(code, company_id)",
        "The short name of the warehouse must be unique per company!",
    )

    # CONSTRAINT METHODS
    # ------------------

    @api.constrains(
        "lot_stock_id",
        "wh_input_stock_loc_id",
        "wh_qc_stock_loc_id",
        "wh_output_stock_loc_id",
        "wh_pack_stock_loc_id",
    )
    def _check_sub_locations_are_inside_the_warehouse(self):
        """Every location the warehouse owns lives under its own view location.

        Nothing else enforces it: `lot_stock_id`'s domain admits any internal
        location of the company, so the form offers another warehouse's stock,
        and the field is not a route trigger — the operation types would keep
        pointing at the location they replaced.
        """
        for warehouse in self:
            view_location = warehouse.view_location_id
            if not view_location:
                continue
            root = view_location.parent_path
            for field_name in warehouse._sub_location_field_names():
                location = warehouse[field_name]
                if not location or not root:
                    continue
                if not (location.parent_path or "").startswith(root):
                    raise ValidationError(
                        _(
                            "%(location)s is not inside warehouse %(warehouse)s, so it "
                            "cannot be its %(field)s.",
                            location=location.display_name,
                            warehouse=warehouse.display_name,
                            field=warehouse._fields[field_name].string,
                        )
                    )

    @api.constrains("resupply_wh_ids")
    def _check_resupply_wh_ids(self):
        for warehouse in self:
            if warehouse in warehouse.resupply_wh_ids:
                raise ValidationError(
                    _(
                        "Warehouse %s cannot be resupplied by itself.",
                        warehouse.display_name,
                    )
                )

    # CRUD METHODS
    # ------------

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
            else:
                vals["code"] = self._normalize_code(vals["code"])
            if "partner_id" not in vals:
                vals["partner_id"] = company.partner_id.id
            taken_names[company.id].add(vals["name"])
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
                ._prepare_sub_location_vals(vals)
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
            new_vals = warehouse._create_or_update_picking_types()
            warehouse.write(new_vals)
            warehouse._create_or_update_route()
            warehouse._create_or_update_global_routes_rules()

            warehouse._create_resupply_routes(warehouse.resupply_wh_ids)

            self.env["stock.location"].browse(
                vals.get("view_location_id")
            )._recompute_descendants_warehouse()

        for partner_id, company_id in {
            (vals["partner_id"], vals["company_id"])
            for vals in vals_list
            if vals.get("partner_id")
        }:
            self._update_partner_transit_locations(partner_id, company_id)

        self._update_multiwarehouse_group()

        return warehouses

    def write(self, vals):
        if vals.get("code"):
            vals = dict(vals, code=self._normalize_code(vals["code"]))
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
        warehouses = self
        warehouses._create_missing_locations(vals)

        if vals.get("reception_steps"):
            warehouses._update_location_reception(vals["reception_steps"])

        if vals.get("delivery_steps"):
            warehouses._update_location_delivery(vals["delivery_steps"])
            warehouses._update_reception_delivery_resupply(vals["delivery_steps"])

        old_resupply_whs = {}
        if vals.get("resupply_wh_ids") and not vals.get("resupply_route_ids"):
            old_resupply_whs = {
                warehouse.id: warehouse.resupply_wh_ids for warehouse in warehouses
            }

        if vals.get("partner_id"):
            if vals.get("company_id"):
                warehouses._update_partner_transit_locations(
                    vals["partner_id"], vals.get("company_id")
                )
            else:
                for warehouse in self:
                    warehouse._update_partner_transit_locations(
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
        warehouses = self
        view_locations = before["view_locations"]
        if view_locations:
            view_locations.exists()._recompute_descendants_warehouse()

        triggers = self._get_fields_route_trigger()
        rule_fields = self._get_global_rule_fields()
        location_fields = frozenset(self._sub_location_field_names())
        changed = vals.keys()
        refresh_picking_types = (
            "code" in changed
            or not triggers.isdisjoint(changed)
            or not location_fields.isdisjoint(changed)
        )
        refresh_routes = not triggers.isdisjoint(changed)
        refresh_global = not self.env.context.get("stock_no_global_route_refresh") and (
            not triggers.isdisjoint(changed) or not rule_fields.isdisjoint(changed)
        )

        for warehouse in warehouses:
            if refresh_picking_types:
                picking_type_vals = warehouse._create_or_update_picking_types()
                if picking_type_vals:
                    warehouse.write(picking_type_vals)
            if refresh_routes:
                warehouse._create_or_update_route()
            if refresh_global:
                warehouse._create_or_update_global_routes_rules()

            if warehouse in before["toggling"]:
                warehouse._toggle_active(vals["active"], triggers)

        if "name" in changed or "code" in changed:
            self.env["stock.picking.type"].with_context(active_test=False).search(
                [("warehouse_id", "in", warehouses.ids)]
            )._update_reference_sequences(only=None if "code" in changed else {"name"})

        for warehouse in warehouses:
            if warehouse.id in before["old_resupply_whs"]:
                warehouse._sync_resupply_routes(
                    before["old_resupply_whs"][warehouse.id]
                )

        if "active" in vals:
            self._update_multiwarehouse_group()

    def unlink(self):
        self._unlink_except_in_use()
        leftovers = [warehouse._collect_owned_records() for warehouse in self]

        for owned in leftovers:
            for records in owned.config:
                records.unlink()
            owned.rules.unlink()
            owned.picking_types.unlink()

        res = super().unlink()

        for owned in leftovers:
            owned.routes.unlink()
            owned.view_location.with_context(stock_unlink_subtree=True).unlink()

        self._update_multiwarehouse_group()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_use(self):
        owned_picking_types = (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search([("warehouse_id", "in", self.ids)])
        )
        self._check_archivable(owned_picking_types, deleting=True)

        locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("id", "child_of", self.view_location_id.ids)])
        )
        if not locations:
            return
        for model, field_name in (
            ("stock.quant", "location_id"),
            ("stock.move", "location_id"),
            ("stock.move", "location_dest_id"),
        ):
            record = self.env[model].search(
                [(field_name, "in", locations.ids)], limit=1
            )
            if not record:
                continue
            raise UserError(
                _(
                    "Warehouse %s has stock or transfer records on its locations, so "
                    "it cannot be deleted. Archive it instead — its history stays "
                    "readable.",
                    self._name_one_of(record[field_name].warehouse_id),
                )
            )

    def _collect_owned_records(self):
        self.ensure_one()
        locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("id", "child_of", self.view_location_id.id)])
        )
        picking_types = (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search([("warehouse_id", "=", self.id)])
        )
        rules = (
            self.env["stock.rule"]
            .with_context(active_test=False)
            .search(
                [
                    "|",
                    ("warehouse_id", "=", self.id),
                    ("picking_type_id", "in", picking_types.ids),
                ]
            )
        )
        routes = self.env["stock.route"].browse()
        for field_name in self._route_field_names():
            routes |= self[field_name]
        routes |= (
            self.env["stock.route"]
            .with_context(active_test=False)
            .search(
                [
                    "|",
                    ("supplied_wh_id", "=", self.id),
                    ("supplier_wh_id", "=", self.id),
                ]
            )
        )
        return OwnedRecords(
            picking_types=picking_types,
            rules=rules,
            routes=routes.filtered(lambda r: len(r.warehouse_ids) <= 1),
            config=(
                self.env["stock.putaway.rule"]
                .with_context(active_test=False)
                .search(
                    [
                        "|",
                        ("location_in_id", "in", locations.ids),
                        ("location_out_id", "in", locations.ids),
                    ]
                ),
                self.env["stock.warehouse.orderpoint"]
                .with_context(active_test=False)
                .search([("warehouse_id", "=", self.id)]),
            ),
            view_location=self.view_location_id,
        )

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

    def _default_name(self):
        return self._generate_default_name(self.env.company)

    # ONCHANGE METHODS
    # ----------------

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

    # ACTION METHODS
    # --------------

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
        return self.search_read(
            [("company_id", "in", self.env.companies.ids)],
            fields=["id", "name", "code"],
        )

    # ACTIVATION METHODS
    # ------------------

    def _toggle_active(self, active, reactivate_depends):
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
        resupply_routes = self._update_resupply_route_activity(active)
        if active:
            dormant = resupply_routes.filtered(lambda route: not route.active)
            if dormant:
                rules = rules.filtered(lambda rule: rule.route_id not in dormant)
        rules.write({"active": active})

        if active:
            values = {depend: self[depend] for depend in reactivate_depends}
            if values:
                self.write(values)
            self._align_resupply_rule_activity()

    def _update_resupply_route_activity(self, active):
        self.ensure_one()
        routes = (
            self.env["stock.route"]
            .with_context(active_test=False)
            .search(
                [
                    "|",
                    ("supplied_wh_id", "=", self.id),
                    ("supplier_wh_id", "=", self.id),
                ]
            )
        )
        if not active:
            routes.filtered("active").write({"active": False})
            return routes
        revivable = routes.filtered(
            lambda route: (
                not route.active
                and route.supplied_wh_id.active
                and route.supplier_wh_id.active
                and route.supplier_wh_id in route.supplied_wh_id.resupply_wh_ids
            )
        )
        if revivable:
            revivable.write({"active": True})
        return routes

    def _check_archivable(self, picking_types, deleting=False):
        """Refuse to archive or delete `self` while anything still points into it.

        `picking_types` are the operation types the warehouses in `self` own, so
        that a caller which has already fetched them does not fetch them again.
        Both searches run with `active_test=False`: an archived operation type of
        another warehouse still holds a foreign key on our locations, and on the
        delete path Postgres, not this guard, would be the one to say so.
        """
        PickingType = self.env["stock.picking.type"].with_context(active_test=False)
        open_moves = self.env["stock.move"]._read_group(
            [
                ("picking_type_id", "in", picking_types.ids),
                ("state", "not in", ("done", "cancel")),
            ],
            ["picking_type_id"],
        )
        if open_moves:
            blocking = PickingType.union(
                *(picking_type for (picking_type,) in open_moves)
            )
            raise UserError(
                _(
                    "You still have ongoing operations for operation types %(operations)s in warehouse %(warehouse)s",
                    operations=blocking.mapped("name"),
                    warehouse=self._name_one_of(blocking.warehouse_id),
                )
            )
        locations = (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("id", "child_of", self.view_location_id.ids)])
        )
        if not locations:
            return
        foreign = PickingType.search(
            [
                "|",
                ("default_location_src_id", "in", locations.ids),
                ("default_location_dest_id", "in", locations.ids),
                ("id", "not in", picking_types.ids),
            ]
        )
        if not foreign:
            return
        owners = (
            foreign.default_location_src_id | foreign.default_location_dest_id
        ).warehouse_id
        message = (
            _(
                "%(operations)s have default source or destination locations within warehouse %(warehouse)s, therefore you cannot delete it.",
                operations=foreign.mapped("name"),
                warehouse=self._name_one_of(owners),
            )
            if deleting
            else _(
                "%(operations)s have default source or destination locations within warehouse %(warehouse)s, therefore you cannot archive it.",
                operations=foreign.mapped("name"),
                warehouse=self._name_one_of(owners),
            )
        )
        raise UserError(message)

    def _name_one_of(self, candidates):
        """Name the warehouse of `self` a message should blame."""
        return ((candidates & self) or self)[:1].display_name

    def _update_multiwarehouse_group(self):
        """Imply the multi-warehouse group while any company has more than one.

        Only the implication is toggled. `res.groups` resolves an implied group
        through `all_implied_by_ids` and never materialises it into `user_ids`,
        so dropping the implication is enough to take the group away — while
        stripping `user_ids` also destroyed every grant an administrator had made
        by hand, and could not tell the two apart.
        """
        group_user = self.env.ref("base.group_user")
        group_multi_warehouses = self.env.ref("stock.group_stock_multi_warehouses")
        group_multi_locations = self.env.ref("stock.group_stock_multi_locations")
        several = bool(
            self.env["stock.warehouse"]
            .sudo()
            ._read_group(
                [("active", "=", True)],
                ["company_id"],
                aggregates=["__count"],
                having=[("__count", ">", 1)],
                limit=1,
            )
        )
        if several == (group_multi_warehouses in group_user.implied_ids):
            return
        if not several:
            group_user.sudo().write(
                {"implied_ids": [fields.Command.unlink(group_multi_warehouses.id)]}
            )
            return
        enabling_locations = group_multi_locations not in group_user.implied_ids
        group_user.sudo().write(
            {
                "implied_ids": [
                    fields.Command.link(group_multi_warehouses.id),
                    fields.Command.link(group_multi_locations.id),
                ]
            }
        )
        if enabling_locations:
            self.sudo()._update_multi_location_defaults(True)

    @api.model
    def _update_multi_location_defaults(self, enabled):
        warehouses = self.env["stock.warehouse"].with_context(active_test=True)
        if enabled:
            warehouses.search([]).int_type_id.active = True
        else:
            warehouses.search(
                [
                    ("reception_steps", "=", "one_step"),
                    ("delivery_steps", "=", "ship_only"),
                ]
            ).int_type_id.active = False
        for xml_id in (
            "stock.view_stock_location_list_2_editable",
            "stock.view_stock_location_form_editable",
        ):
            view = self.env.ref(xml_id, raise_if_not_found=False)
            if view:
                view.active = not enabled

    # LOCATION METHODS
    # ----------------

    @ormcache()
    def _sub_location_field_names(self):
        return tuple(self._prepare_sub_location_vals({}))

    def _get_fields_location_step(self):
        return ["reception_steps", "delivery_steps", "company_id"]

    def _get_location_step_values(self, vals, code=False):
        field_names = self._get_fields_location_step()
        values = {name: vals[name] for name in field_names if name in vals}
        missing = [name for name in field_names if name not in values]
        record = self if len(self) == 1 else self.browse()
        if missing:
            defaults = {} if record else self.default_get(missing)
            for name in missing:
                if not record:
                    values[name] = defaults[name]
                    continue
                value = record[name]
                values[name] = (
                    value.id if isinstance(value, models.BaseModel) else value
                )
        values["code"] = self._normalize_code(
            vals.get("code") or code or (record.code if record else "")
        )
        return values

    def _prepare_sub_location_vals(self, vals, code=False):
        def_values = self._get_location_step_values(vals, code)
        reception_steps = def_values["reception_steps"]
        delivery_steps = def_values["delivery_steps"]
        code = def_values["code"]
        return {
            "lot_stock_id": {
                "name": _("Stock"),
                "active": True,
                "usage": "internal",
                "replenish_location": True,
                "barcode": code + "STOCK",
            },
            "wh_input_stock_loc_id": {
                "name": _("Input"),
                "active": reception_steps != "one_step",
                "usage": "internal",
                "barcode": code + "INPUT",
            },
            "wh_qc_stock_loc_id": {
                "name": _("Quality Control"),
                "active": reception_steps == "three_steps",
                "usage": "internal",
                "barcode": code + "QUALITY",
            },
            "wh_output_stock_loc_id": {
                "name": _("Output"),
                "active": delivery_steps != "ship_only",
                "usage": "internal",
                "barcode": code + "OUTPUT",
            },
            "wh_pack_stock_loc_id": {
                "name": _("Packing Zone"),
                "active": delivery_steps == "pick_pack_ship",
                "usage": "internal",
                "barcode": code + "PACKING",
            },
        }

    @api.model
    def _resolve_barcodes(self, values_list, company_id, ignore_location_ids=()):
        wanted = {values["barcode"] for values in values_list if values.get("barcode")}
        if not wanted:
            return
        domain = [("barcode", "in", list(wanted)), ("company_id", "=", company_id)]
        if ignore_location_ids:
            domain.append(("id", "not in", list(ignore_location_ids)))
        taken = {
            row["barcode"]: row["complete_name"]
            for row in self.env["stock.location"]
            .with_context(active_test=False)
            .search_read(domain, ["barcode", "complete_name"])
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
        location_fields = self._sub_location_field_names()
        for warehouse in self:
            if all(warehouse[field] or field in vals for field in location_fields):
                continue
            company_id = vals.get("company_id", warehouse.company_id.id)
            sub_locations = warehouse._prepare_sub_location_vals(
                dict(vals, company_id=company_id), warehouse.code
            )
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

    def _update_location_barcodes(self, new_code):
        for warehouse in self:
            values = warehouse._prepare_sub_location_vals({}, new_code)
            locations = self.env["stock.location"].browse()
            wanted = []
            for field_name, location_values in values.items():
                location = warehouse[field_name]
                if not location or not location_values.get("barcode"):
                    continue
                locations |= location
                wanted.append((location, {"barcode": location_values["barcode"]}))
            if not wanted:
                continue
            warehouse._resolve_barcodes(
                [values for _location, values in wanted],
                warehouse.company_id.id,
                ignore_location_ids=locations.ids,
            )
            for location, location_values in wanted:
                location.barcode = location_values["barcode"]

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

    def _get_input_output_locations(self):
        return (
            (
                self.lot_stock_id
                if self.reception_steps == "one_step"
                else self.wh_input_stock_loc_id
            ),
            (
                self.lot_stock_id
                if self.delivery_steps == "ship_only"
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
        """The customer or vendor location, by xmlid, then by usage.

        The fallback is ordered: `limit=1` over an unordered search hands back
        whichever row Postgres happened to return, so two calls in one request
        could disagree about where goods leave the company for. Company-owned
        locations come first, since a database that has lost the xmlid has more
        than one candidate.
        """
        location = self.env.ref(
            PARTNER_LOCATION_XML_IDS[usage], raise_if_not_found=False
        )
        if not location:
            location = self.env["stock.location"].search(
                [
                    ("usage", "=", usage),
                    ("company_id", "in", [False, self.env.company.id]),
                ],
                order="company_id, id",
                limit=1,
            )
        if location:
            return location
        raise UserError(
            self.env._(PARTNER_LOCATION_MISSING[usage])  # pylint: disable=gettext-variable
        )

    @api.model
    def _get_partner_locations(self):
        return (
            self._get_partner_location("customer"),
            self._get_partner_location("supplier"),
        )

    def _get_production_location(self):
        location = self.env["stock.location"].search(
            [("usage", "=", "production"), ("company_id", "=", self.company_id.id)],
            limit=1,
        )
        if not location:
            raise UserError(_("Can't find any production location."))
        return location

    # OPERATION TYPE METHODS
    # ----------------------

    def _create_or_update_picking_types(self):
        self.ensure_one()
        PickingType = self.env["stock.picking.type"]

        warehouse_data = {}
        data = self._prepare_picking_type_update_vals()
        create_data = self._prepare_picking_type_create_vals()
        codes = self._get_picking_type_codes()
        suffixes = self._get_picking_type_barcode_suffixes(codes)
        self._check_picking_type_registry(data, create_data, suffixes, codes)
        self._update_picking_type_barcodes(data, suffixes)

        to_update = [field for field in data if self[field]]
        to_create = [field for field in data if not self[field]]

        for field in to_update:
            self[field].write(data[field])
        if to_update:
            PickingType.browse(
                self[field].id for field in to_update
            )._update_reference_sequences(only={"company_id"})

        if to_create:
            color = self._get_picking_type_color()
            base_sequence = self._get_last_picking_type_sequence()
            picking_type_vals = []
            for offset, field in enumerate(to_create, start=1):
                values = dict(data[field], **create_data[field])
                values.update(
                    warehouse_id=self.id,
                    color=color,
                    sequence_code=codes[field],
                    sequence=base_sequence + offset,
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

    def _get_picking_type_color(self):
        self.ensure_one()
        used = {
            row["color"]
            for row in self.env["stock.picking.type"].search_read(
                [
                    ("warehouse_id", "!=", False),
                    ("color", "!=", False),
                    ("company_id", "=", self.company_id.id),
                ],
                ["color"],
            )
        }
        return next((color for color in range(12) if color not in used), 0)

    def _get_last_picking_type_sequence(self):
        rows = (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search_read(
                [("sequence", "!=", False)],
                ["sequence"],
                limit=1,
                order="sequence desc",
            )
        )
        return (rows and rows[0]["sequence"]) or 0

    @api.model
    def _check_picking_type_registry(self, update_data, create_data, suffixes, codes):
        expected = set(codes)
        for label, mapping in (
            ("_prepare_picking_type_update_vals", update_data),
            ("_prepare_picking_type_create_vals", create_data),
            ("_get_picking_type_barcode_suffixes", suffixes),
        ):
            missing = expected - set(mapping)
            extra = set(mapping) - expected
            if missing or extra:
                raise ValueError(
                    "stock.warehouse picking-type declarations disagree: "
                    "%s is missing %s and declares unregistered %s. Every "
                    "picking type must appear in _get_picking_type_codes, "
                    "_prepare_picking_type_create_vals, "
                    "_prepare_picking_type_update_vals and "
                    "_get_picking_type_barcode_suffixes."
                    % (label, sorted(missing) or "nothing", sorted(extra) or "nothing")
                )

    def _get_picking_type_codes(self):
        return dict(WAREHOUSE_PICKING_TYPE_CODES)

    def _get_picking_type_barcode_suffixes(self, codes=None):
        """Barcode suffix per operation type, defaulting to its sequence code.

        `codes` is passed by a caller that has already read them: with
        mrp_subcontracting installed `_get_picking_type_codes` counts sequences to
        pick its own, so reading it twice is a query, and two readings a
        transaction apart could disagree.
        """
        return dict(codes if codes is not None else self._get_picking_type_codes())

    def _update_picking_type_barcodes(self, update_data, suffixes):
        self.ensure_one()
        code = self._normalized_code()
        for field, suffix in suffixes.items():
            update_data[field]["barcode"] = code + suffix

    def _prepare_picking_type_update_vals(self):
        input_loc, output_loc = self._get_input_output_locations()
        return {
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

    def _prepare_picking_type_create_vals(self):
        _input_loc, output_loc = self._get_input_output_locations()
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

    # ROUTING METHODS
    # ---------------

    @ormcache()
    def _route_field_names(self):
        return tuple(
            name
            for name, field in self._fields.items()
            if field.type == "many2one" and field.comodel_name == "stock.route"
        )

    def _get_fields_route_trigger(self):
        """Warehouse fields whose change must regenerate routes and rules.

        This is a *declaration*, not a derivation: a module adding a route or a
        global rule extends it alongside the payload builder that reads those
        fields. `test_route_trigger_fields_are_declared` fails if the two ever
        disagree, which is what a runtime probe used to buy at the cost of
        executing every builder — and of a three-tier fallback for the warehouses
        on which a builder raises.
        """
        return frozenset({"reception_steps", "delivery_steps"})

    def _get_global_rule_fields(self):
        """Warehouse fields holding a rule that lives on a global route."""
        return frozenset({"mto_pull_id"})

    def _create_or_update_route(self):
        self.ensure_one()
        routes = []
        field_vals = {}
        rules_dict = self._get_rules_dict()
        for route_field, route_data in self._prepare_route_vals().items():
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
            if routing_key not in rules_dict[self.id]:
                raise ValueError(
                    "stock.warehouse route %r declares routing_key %r, which "
                    "_get_rules_dict does not answer. Every entry of "
                    "_prepare_route_vals needs a routing_key that "
                    "_get_rules_dict knows, and a module adding a route extends "
                    "both." % (route_field, routing_key)
                )
            rules = rules_dict[self.id][routing_key]
            if "rules_values" in route_data:
                route_data["rules_values"].update({"route_id": route.id})
            else:
                route_data["rules_values"] = {"route_id": route.id}
            rules_list = self._prepare_rule_vals(
                rules, values=route_data["rules_values"]
            )
            self._find_existing_rule_or_create(rules_list)
            if route_data["route_create_values"].get(
                "warehouse_selectable", False
            ) or route_data.get("route_update_values", {}).get(
                "warehouse_selectable", False
            ):
                routes.append(route)
        field_vals["route_ids"] = [fields.Command.link(route.id) for route in routes]
        self.write(field_vals)
        return field_vals

    def _prepare_route_vals(self):
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

    def _prepare_receive_route_vals(self, installed_depends):
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

    def _create_or_update_global_routes_rules(self):
        new_rule_ids = {}
        for (
            rule_field,
            rule_details,
        ) in self._prepare_routable_global_route_rule_vals().items():
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

    def _get_or_create_global_route(
        self,
        xml_id,
        route_name,
        create=True,
        raise_if_not_found=False,
    ):
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
            if data_route and create:
                route = data_route.copy(
                    {
                        "name": route_name,
                        "company_id": company.id,
                        "rule_ids": False,
                    },
                )
        return route

    def _prepare_routable_global_route_rule_vals(self):
        vals = self._prepare_global_route_rule_vals()
        return {
            k: v
            for k, v in vals.items()
            if v.get("create_values", {}).get("route_id", True)
            and v.get("update_values", {}).get("route_id", True)
        }

    def _prepare_global_route_rule_vals(self):
        delivery_rules = self._get_rules_dict()[self.id][self.delivery_steps]
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
                    "route_id": self._get_or_create_global_route(
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

    def _get_rules_dict(self):
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

    def _find_existing_rule_or_create(self, rules_list):
        Rule = self.env["stock.rule"]
        if not rules_list:
            return
        identity = (
            "picking_type_id",
            "location_src_id",
            "location_dest_id",
            "route_id",
        )
        wanted = {
            tuple(rule_vals[name] for name in identity) + (rule_vals["action"],)
            for rule_vals in rules_list
        }
        candidates = Rule.with_context(active_test=False).search(
            [
                (name, "in", list({key[position] for key in wanted}))
                for position, name in enumerate(identity)
            ]
        )
        existing = {}
        for rule in candidates:
            key = (
                rule.picking_type_id.id,
                rule.location_src_id.id,
                rule.location_dest_id.id,
                rule.route_id.id,
                rule.action,
            )
            existing.setdefault(key, rule)
        to_create = []
        for rule_vals in rules_list:
            key = tuple(rule_vals[name] for name in identity) + (rule_vals["action"],)
            rule = existing.get(key)
            if not rule:
                to_create.append(rule_vals)
                continue
            changed = {
                name: value
                for name, value in rule_vals.items()
                if name not in identity and self._rule_value_differs(rule, name, value)
            }
            if changed:
                rule.write(changed)
        if to_create:
            Rule.create(to_create)

    @api.model
    def _rule_value_differs(self, rule, field_name, value):
        """Whether an existing rule already carries the value we would write.

        A rule matching the identity above is *the* rule for that leg, so the
        rest of its values are ours to keep current. Reactivating it and leaving
        the rest alone made a warehouse's behaviour depend on the configuration
        it used to have: a receipt rule created while the warehouse received in
        one step keeps `propagate_cancel=False` after a move to two steps, where
        a warehouse created in two steps has it set, so cancelling the receipt
        cancels the storage transfer on one and orphans it on the other.
        """
        current = rule[field_name]
        if isinstance(current, models.BaseModel):
            return current.id != (value or False)
        return current != value

    def _prepare_rule_vals(self, routings, values=None, name_suffix=""):
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

    def _prepare_supply_pull_rule_vals(self, routings, values=None):
        pull_values = dict(values or {})
        pull_values["active"] = True
        rules_list = self._prepare_rule_vals(routings, values=pull_values)
        for pull_rules in rules_list:
            pull_rules["procure_method"] = (
                "make_to_order"
                if self.lot_stock_id.id != pull_rules["location_src_id"]
                else "make_to_stock"
            )
        return rules_list

    def _get_all_routes(self):
        routes = self.route_ids | self.mto_pull_id.route_id
        routes |= (
            self.env["stock.route"]
            .with_context(active_test=False)
            .search([("supplied_wh_id", "in", self.ids)])
        )
        return routes

    def _get_route_name(self, route_type):
        if route_type not in ROUTE_NAMES:
            raise UserError(
                _(
                    "No route name is declared for the routing configuration %s.",
                    route_type,
                )
            )
        return self.env._(ROUTE_NAMES[route_type])  # pylint: disable=gettext-variable

    # RESUPPLY METHODS
    # ----------------

    def _sync_resupply_routes(self, previous_resupply_whs):
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
                self._create_resupply_routes(remaining_to_add)
        if to_remove:
            to_disable_route_ids = Route.search(
                [
                    ("supplied_wh_id", "=", self.id),
                    ("supplier_wh_id", "in", to_remove.ids),
                    ("active", "=", True),
                ]
            )
            to_disable_route_ids.action_archive()

    def _create_resupply_routes(self, supplier_warehouses):
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
                supplier_wh._create_resupply_mto_rules([output_to_transit])

            inter_wh_route = Route.create(
                self._prepare_inter_warehouse_route_vals(supplier_wh)
            )

            pull_rules_list = supplier_wh._prepare_supply_pull_rule_vals(
                [output_to_transit],
                values={"route_id": inter_wh_route.id, "location_dest_from_rule": True},
            )
            if supplier_wh.delivery_steps != "ship_only":
                pull_rules_list += supplier_wh._prepare_supply_pull_rule_vals(
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
            pull_rules_list += self._prepare_supply_pull_rule_vals(
                [
                    self.Routing(
                        transit_location, self.lot_stock_id, self.in_type_id, "pull"
                    )
                ],
                values={"route_id": inter_wh_route.id},
            )
            Rule.create(pull_rules_list)

    def _create_resupply_mto_rules(self, routings):
        self.ensure_one()
        if not routings:
            return
        mto_vals = self._prepare_routable_global_route_rule_vals().get("mto_pull_id")
        if not mto_vals:
            return
        self._find_existing_rule_or_create(
            self._prepare_rule_vals(
                routings, mto_vals["create_values"], name_suffix="MTO"
            )
        )

    def _prepare_inter_warehouse_route_vals(self, supplier_warehouse):
        return {
            "name": self._format_resupply_routename(self.name, supplier_warehouse.name),
            "warehouse_selectable": True,
            "product_selectable": True,
            "product_categ_selectable": True,
            "supplied_wh_id": self.id,
            "supplier_wh_id": supplier_warehouse.id,
            "company_id": (self.company_id & supplier_warehouse.company_id).id,
        }

    def _update_reception_delivery_resupply(self, delivery_new):
        if not delivery_new:
            return
        for warehouse in self:
            if warehouse.delivery_steps == delivery_new:
                continue
            if "ship_only" not in (warehouse.delivery_steps, delivery_new):
                continue
            change_to_multiple = warehouse.delivery_steps == "ship_only"
            output_loc = (
                warehouse.lot_stock_id
                if delivery_new == "ship_only"
                else warehouse.wh_output_stock_loc_id
            )
            warehouse._update_delivery_resupply(output_loc, change_to_multiple)

    def _get_resupply_routes(self):
        self.ensure_one()
        return self.env["stock.route"].search([("supplier_wh_id", "=", self.id)])

    def _get_resupply_pick_leg_domain(self, routes):
        self.ensure_one()
        return [
            ("route_id", "in", routes.ids),
            ("action", "!=", "push"),
            ("location_dest_id", "=", self.wh_output_stock_loc_id.id),
            ("picking_type_id", "=", self.pick_type_id.id),
        ]

    def _get_resupply_mto_leg_domain(self):
        self.ensure_one()
        mto_route = self._get_or_create_global_route(
            "stock.route_warehouse0_mto",
            _("Replenish on Order (MTO)"),
            create=False,
        )
        if not mto_route:
            return False
        return [
            ("route_id", "=", mto_route.id),
            ("action", "!=", "push"),
            ("location_dest_id.usage", "=", "transit"),
            ("location_src_id", "=", self.lot_stock_id.id),
            ("warehouse_id", "=", self.id),
        ]

    def _update_delivery_resupply(self, new_location, change_to_multiple):
        self.ensure_one()
        Rule = self.env["stock.rule"]
        routes = self._get_resupply_routes()
        if not routes:
            return
        transit_legs = Rule.search(
            [
                ("route_id", "in", routes.ids),
                ("action", "!=", "push"),
                ("location_dest_id.usage", "=", "transit"),
            ]
        )
        transit_legs.write(
            {
                "location_src_id": new_location.id,
                "procure_method": "make_to_order"
                if change_to_multiple
                else "make_to_stock",
            }
        )
        if change_to_multiple:
            existing = Rule.with_context(active_test=False).search(
                self._get_resupply_pick_leg_domain(routes)
            )
            missing_rule_vals = []
            for route in routes - existing.route_id:
                missing_rule_vals += self._prepare_supply_pull_rule_vals(
                    [
                        self.Routing(
                            self.lot_stock_id, new_location, self.pick_type_id, "pull"
                        )
                    ],
                    values={"route_id": route.id},
                )
            Rule.create(missing_rule_vals)
        else:
            self._create_resupply_mto_rules(
                [
                    self.Routing(self.lot_stock_id, location, self.out_type_id, "pull")
                    for location in transit_legs.location_dest_id
                ]
            )
        self._align_resupply_rule_activity(multi_step=change_to_multiple)

    def _align_resupply_rule_activity(self, multi_step=None):
        self.ensure_one()
        Rule = self.env["stock.rule"].with_context(active_test=False)
        routes = self._get_resupply_routes()
        if not routes:
            return
        if multi_step is None:
            multi_step = self.delivery_steps != "ship_only"
        Rule.search(self._get_resupply_pick_leg_domain(routes)).write(
            {"active": multi_step}
        )
        mto_domain = self._get_resupply_mto_leg_domain()
        if mto_domain:
            Rule.search(mto_domain).write({"active": not multi_step})

    # NAMING METHODS
    # --------------

    def _existing_warehouse_values(self, field_name, company, taken=()):
        return set(taken) | set(
            self.env["stock.warehouse"]
            .with_context(active_test=False)
            .search([("company_id", "=", company.id)])
            .mapped(field_name)
        )

    def _generate_default_name(self, company, taken=()):
        existing = self._existing_warehouse_values("name", company, taken)
        if not existing:
            return company.name
        counter = len(existing) + 1
        while True:
            candidate = _(
                "%(company)s - warehouse # %(counter)s",
                company=company.name,
                counter=counter,
            )
            if candidate not in existing:
                return candidate
            counter += 1

    def _generate_default_code(self, company, taken=()):
        base = self._normalize_code(company.name)[:5] or "WH"
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

    def _unique_copy_name(self, base, company, taken=()):
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
    def _normalize_code(self, code):
        return (code or "").replace(" ", "").upper()

    def _normalized_code(self):
        self.ensure_one()
        return self._normalize_code(self.code)

    def _update_name_and_code(self, new_name=False, new_code=False):
        """Rename what carries the old name or code in its own text.

        Reference sequences are not touched here: they are rebuilt from the
        warehouse after the write, by `_update_reference_sequences`, which is
        their single authority.
        """
        if new_code:
            self.view_location_id.write({"name": new_code})
            self._update_rule_names(new_code)
            self._update_location_barcodes(new_code)
        if new_name:
            self._update_route_names(new_name)

    def _update_route_names(self, new_name):
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
        rules = (
            self.env["stock.rule"]
            .with_context(active_test=False)
            .search([("warehouse_id", "in", self.ids)])
        )
        new_prefix = "%s: " % new_code
        old_prefixes = {warehouse.id: "%s: " % warehouse.code for warehouse in self}
        by_new_name = defaultdict(list)
        for rule in rules:
            old_prefix = old_prefixes.get(rule.warehouse_id.id)
            if old_prefix and rule.name and rule.name.startswith(old_prefix):
                by_new_name[new_prefix + rule.name[len(old_prefix) :]].append(rule.id)
        Rule = self.env["stock.rule"].with_context(active_test=False)
        for name, rule_ids in by_new_name.items():
            Rule.browse(rule_ids).write({"name": name})

    def _format_rulename(self, from_loc, dest_loc, suffix):
        rulename = "%s: %s" % (self._normalized_code(), from_loc.name)
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

    @api.model
    def _format_resupply_routename(self, supplied_name, supplier_name):
        return _(
            "%(warehouse)s: Supply Product from %(supplier)s",
            warehouse=supplied_name,
            supplier=supplier_name,
        )

    # HELPER METHODS
    # --------------

    @api.model
    def _update_partner_transit_locations(self, partner_id, company_id):
        """Route a warehouse address through the company's inter-warehouse transit.

        A company with no transit location is not a reason to blank the partner's
        own locations: `purchase.order` refuses to confirm without a vendor
        location, so clearing them here breaks a document this module never sees.
        """
        if not partner_id:
            return
        company = (
            self.env["res.company"].browse(company_id)
            if company_id
            else self.env.company
        )
        transit_location = company.internal_transit_location_id
        if not transit_location:
            return
        self.env["res.partner"].browse(partner_id).with_company(
            company
        )._set_stock_property_locations(transit_location)

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
