import json
from collections import defaultdict
from collections.abc import Iterable

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.barcode import check_barcode_encoding
from odoo.libs.numbers import float_is_zero, float_round
from odoo.tools import format_list

from ..const import INVENTORY_REFERENCE_PACKAGE_RELOCATED
from odoo.addons.base.models.ir_actions import eval_action_context


class StockPackage(models.Model):
    _name = "stock.package"
    _description = "Package"
    _order = "name, id"
    _parent_name = "parent_package_id"
    _parent_store = True
    _rec_name = "complete_name"
    _rec_names_search = ["complete_name", "dest_complete_name", "name"]

    name = fields.Char(
        string="Package Reference",
        required=True,
        copy=False,
        index="trigram",
    )
    complete_name = fields.Char(
        string="Full Package Name",
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    dest_complete_name = fields.Char(
        string="Package Name At Destination",
        compute="_compute_dest_complete_name",
        store=True,
        recursive=True,
    )
    quant_ids = fields.One2many(
        comodel_name="stock.quant",
        inverse_name="package_id",
        string="Bulk Content",
        readonly=True,
        domain=["|", ("quantity", "!=", 0), ("reserved_quantity", "!=", 0)],
    )
    contained_quant_ids = fields.One2many(
        comodel_name="stock.quant",
        compute="_compute_contained_quant_ids",
        search="_search_contained_quant_ids",
    )
    content_description = fields.Char(
        string="Contents", compute="_compute_content_description"
    )
    package_type_id = fields.Many2one(
        comodel_name="stock.package.type",
        string="Package Type",
        index=True,
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location",
        compute="_compute_package_info",
        store=True,
        recursive=True,
        readonly=False,
        index=True,
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination location",
        compute="_compute_location_dest_id",
        search="_search_location_dest_id",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        compute="_compute_package_info",
        store=True,
        recursive=True,
        readonly=True,
        index=True,
    )
    owner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Owner",
        compute="_compute_owner_id",
        compute_sudo=True,
        readonly=True,
        search="_search_owner_id",
    )
    parent_package_id = fields.Many2one(
        comodel_name="stock.package",
        string="Container",
        index="btree_not_null",
    )
    child_package_ids = fields.One2many(
        comodel_name="stock.package",
        inverse_name="parent_package_id",
        string="Contained Packages",
    )
    all_children_package_ids = fields.One2many(
        comodel_name="stock.package",
        compute="_compute_all_children_package_ids",
        search="_search_all_children_package_ids",
    )
    package_dest_id = fields.Many2one(
        comodel_name="stock.package",
        string="Destination Container",
        index="btree_not_null",
    )
    outermost_package_id = fields.Many2one(
        comodel_name="stock.package",
        string="Outermost Destination Container",
        compute="_compute_outermost_package_id",
        store=True,
        recursive=True,
        index="btree_not_null",
    )
    child_package_dest_ids = fields.One2many(
        comodel_name="stock.package",
        inverse_name="package_dest_id",
        string="Assigned Contained Packages",
    )
    result_move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="result_package_id",
        string="Move Lines Targeting This Package",
    )
    move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        compute="_compute_move_line_ids",
        search="_search_move_line_ids",
        recursive=True,
    )
    picking_ids = fields.Many2many(
        comodel_name="stock.picking",
        string="Transfers",
        compute="_compute_picking_ids",
        search="_search_picking_ids",
        help="Transfers in which the Package is set as Destination Package",
    )
    shipping_weight = fields.Float(
        string="Shipping Weight",
        digits="Stock Weight",
        help="Total weight of the package.",
    )
    valid_sscc = fields.Boolean(
        string="Package name is valid SSCC",
        compute="_compute_valid_sscc",
    )
    pack_date = fields.Date(string="Pack Date", default=fields.Date.context_today)
    parent_path = fields.Char(index=True)
    json_popover = fields.Char(
        string="JSON data for popover widget",
        compute="_compute_json_popover",
    )

    @api.model_create_multi
    def create(self, vals_list):
        new_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            if vals.get("complete_name"):
                vals["name"] = vals.pop("complete_name")
            if not vals.get("name"):
                package_type = self.env["stock.package.type"].browse(
                    vals.get("package_type_id")
                )
                vals["name"] = package_type._get_next_name_by_sequence()
            new_vals_list.append(vals)

        return super().create(new_vals_list)

    def write(self, vals):
        if "name" in vals and not vals.get("name"):
            vals = {key: value for key, value in vals.items() if key != "name"}
            for package in self:
                package_type = self.env["stock.package.type"].browse(
                    vals.get("package_type_id", package.package_type_id.id)
                )
                package.name = package_type._get_next_name_by_sequence()
        if "location_id" in vals:
            empty_packs = self.filtered(lambda pack: not pack.contained_quant_ids)
            if not vals["location_id"] and self - empty_packs:
                raise UserError(_("Cannot remove the location of a non empty package"))
            if vals["location_id"]:
                if empty_packs:
                    raise UserError(_("Cannot move an empty package"))
                location_dest_id = self.env["stock.location"].browse(
                    vals["location_id"]
                )
                quant_to_move = self.contained_quant_ids.filtered(
                    lambda q: q.product_uom_id.compare(q.quantity, 0) > 0
                )
                quant_to_move.move_quants(
                    location_dest_id,
                    message=INVENTORY_REFERENCE_PACKAGE_RELOCATED,
                    up_to_parent_packages=self,
                )
                negative_quants = self.contained_quant_ids.filtered(
                    lambda q: q.product_uom_id.compare(q.quantity, 0) < 0
                )
                if negative_quants:
                    message = INVENTORY_REFERENCE_PACKAGE_RELOCATED
                    moves = self.env["stock.move"].create(
                        [
                            quant.with_context(
                                inventory_name=message
                            )._get_inventory_move_values(
                                -quant.quantity,
                                location_dest_id,
                                quant.location_id,
                                quant.package_id,
                                quant.package_id,
                            )
                            for quant in negative_quants
                        ]
                    )
                    moves._action_done()
        return super().write(vals)

    @api.constrains("package_dest_id")
    def _check_package_dest_is_not_a_descendant(self):
        for package in self:
            if not package.package_dest_id:
                continue
            if (
                package.package_dest_id.id
                in package._get_all_children_package_dest_ids()[1]
            ):
                raise ValidationError(
                    _(
                        "A package can't have one of its contained packages as destination container."
                    ),
                )

    @api.depends("child_package_ids", "child_package_ids.parent_path")
    def _compute_all_children_package_ids(self):
        def fetch_all_children(parent_id, children_by_pack):
            children_ids = children_by_pack.get(parent_id, [])
            sub_children_ids = [
                cid
                for child_id in children_ids
                for cid in fetch_all_children(child_id, children_by_pack)
            ]
            return children_ids + sub_children_ids

        groups = self.env["stock.package"]._read_group(
            [("id", "child_of", self.ids)], ["parent_package_id"], ["id:array_agg"]
        )
        children_by_pack = {
            package.id: children_ids for package, children_ids in groups
        }
        for package in self:
            package.all_children_package_ids = [
                Command.set(fetch_all_children(package.id, children_by_pack))
            ]

    @api.depends(
        "complete_name",
        "package_type_id.packaging_length",
        "package_type_id.width",
        "package_type_id.height",
    )
    @api.depends_context(
        "formatted_display_name", "show_dest_package", "show_src_package", "is_done"
    )
    def _compute_display_name(self):
        show_dest_package = self.env.context.get("show_dest_package")
        show_src_package = self.env.context.get("show_src_package")
        is_done = self.env.context.get("is_done")
        formatted = self.env.context.get("formatted_display_name")
        for package in self:
            if is_done:
                display_name = package.name
            elif show_dest_package:
                display_name = package.dest_complete_name
            elif show_src_package:
                display_name = package.complete_name
            else:
                display_name = package.name

            if (
                formatted
                and package.package_type_id
                and package.package_type_id.packaging_length
                and package.package_type_id.width
                and package.package_type_id.height
            ):
                package.display_name = f"{display_name}\t--{package.package_type_id.packaging_length} x {package.package_type_id.width} x {package.package_type_id.height}--"
            else:
                package.display_name = display_name

    def _compute_path_name(self, parent_field, name_field):
        for package in self:
            parent = package[parent_field]
            package[name_field] = (
                f"{parent[name_field]} > {package.name}" if parent else package.name
            )

    @api.depends("name", "parent_package_id.complete_name")
    def _compute_complete_name(self):
        self._compute_path_name("parent_package_id", "complete_name")

    @api.depends("name", "package_dest_id.dest_complete_name")
    def _compute_dest_complete_name(self):
        self._compute_path_name("package_dest_id", "dest_complete_name")

    @api.depends("quant_ids", "all_children_package_ids.quant_ids")
    def _compute_contained_quant_ids(self):
        for package in self:
            package.contained_quant_ids = (
                package.quant_ids | package.all_children_package_ids.quant_ids
            )

    @api.depends("contained_quant_ids.quantity", "contained_quant_ids.product_id")
    def _compute_content_description(self):
        precision = self.env["decimal.precision"].precision_get("Product Unit")

        def format_content(product, qty):
            qty = float_round(qty, precision_digits=precision)
            quantity = str(int(qty) if qty == int(qty) else qty)
            if display_uom:
                return f"{quantity} {product.uom_id.name} {product.display_name}"
            return f"{quantity} {product.display_name}"

        display_uom = self.env.user.has_group("uom.group_uom")
        for package in self:
            package.content_description = format_list(
                self.env,
                [
                    format_content(product, sum(quants.mapped("quantity")))
                    for product, quants in package.contained_quant_ids.grouped(
                        "product_id"
                    ).items()
                ],
            )

    @api.depends("move_line_ids", "move_line_ids.location_dest_id")
    def _compute_json_popover(self):
        for package in self:
            if not package._has_issues():
                package.json_popover = False
                continue
            location_names = package.move_line_ids.location_dest_id.mapped(
                "display_name"
            )
            package.json_popover = json.dumps(
                {
                    "title": _("Multiple destinations"),
                    "msg": _(
                        "This package is currently set to be sent in %(location_names_list)s.",
                        location_names_list=location_names,
                    ),
                    "color": "text-warning",
                    "icon": "fa-exclamation-triangle",
                },
            )

    @api.depends("move_line_ids.location_dest_id")
    def _compute_location_dest_id(self):
        for package in self:
            locations = package.move_line_ids.location_dest_id
            package.location_dest_id = locations if len(locations) == 1 else False

    @api.depends(
        "result_move_line_ids",
        "result_move_line_ids.state",
        "child_package_dest_ids",
        "child_package_dest_ids.move_line_ids",
    )
    def _compute_move_line_ids(self):
        children_by_dest_pack, all_pack_ids = self._get_all_children_package_dest_ids()
        groups = self.env["stock.move.line"]._read_group(
            domain=[
                ("state", "not in", ["done", "cancel"]),
                ("result_package_id", "in", all_pack_ids),
            ],
            groupby=["result_package_id"],
            aggregates=["id:array_agg"],
        )
        move_lines_by_package = {
            package.id: move_line_ids for package, move_line_ids in groups
        }

        for package in self:
            move_line_ids = {
                line_id
                for child_id in children_by_dest_pack[package]
                for line_id in move_lines_by_package.get(child_id, [])
            }
            move_line_ids.update(move_lines_by_package.get(package.id, []))
            package.move_line_ids = [Command.set(list(move_line_ids))]

    @api.depends(
        "child_package_ids",
        "child_package_ids.location_id",
        "quant_ids",
        "quant_ids.quantity",
        "quant_ids.location_id",
        "quant_ids.company_id",
    )
    def _compute_package_info(self):
        for package in self:
            package.location_id = False
            package.company_id = False
            quants = package.quant_ids.filtered(
                lambda q: q.product_uom_id.compare(q.quantity, 0) > 0
            )
            if quants:
                locations = quants.location_id
                if len(locations) == 1:
                    package.location_id = locations
                companies = quants.company_id
                if len(companies) == 1 and all(q.company_id for q in quants):
                    package.company_id = companies
            elif package.child_package_ids:
                locations = package.child_package_ids.location_id
                if len(locations) == 1:
                    package.location_id = locations
                companies = package.child_package_ids.company_id
                if len(companies) == 1 and all(
                    p.company_id for p in package.child_package_ids
                ):
                    package.company_id = companies

    @api.depends("move_line_ids")
    def _compute_picking_ids(self):
        for package in self:
            package.picking_ids = package.move_line_ids.picking_id

    @api.depends("contained_quant_ids.owner_id")
    def _compute_owner_id(self):
        for package in self:
            package.owner_id = False
            quants = package.contained_quant_ids
            if quants and all(q.owner_id == quants[0].owner_id for q in quants):
                package.owner_id = quants[0].owner_id

    @api.depends("package_dest_id", "package_dest_id.outermost_package_id")
    def _compute_outermost_package_id(self):
        for package in self:
            if package.package_dest_id:
                package.outermost_package_id = (
                    package.package_dest_id.outermost_package_id
                )
            else:
                package.outermost_package_id = package

    @api.depends("name")
    def _compute_valid_sscc(self):
        for package in self:
            package.valid_sscc = bool(package.name) and check_barcode_encoding(
                package.name, "sscc"
            )

    def _search_all_children_package_ids(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        packages = self.search_fetch(
            domain=[("id", operator, value)], field_names=["id"]
        )
        return Domain("id", "parent_of", packages.ids) & Domain(
            "id", "not in", packages.ids
        )

    def _search_contained_quant_ids(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        packages = self.search([("quant_ids", operator, value)])
        if packages:
            return [("id", "parent_of", packages.ids)]
        else:
            return [("id", "=", False)]

    def _packages_of_move_lines(self, domain):
        move_lines = self.env["stock.move.line"].search_fetch(
            domain=Domain("state", "not in", ["done", "cancel"]) & Domain(domain),
            field_names=["result_package_id"],
        )
        return move_lines.result_package_id._get_all_package_dest_ids()

    def _search_location_dest_id(self, operator, value):
        if operator != "in":
            return NotImplemented
        here = self._packages_of_move_lines(Domain("location_dest_id", "in", value))
        elsewhere = self._packages_of_move_lines(
            Domain("location_dest_id", "not in", value)
        )
        return [("id", "in", list(set(here) - set(elsewhere)))]

    def _search_move_line_ids(self, operator, value):
        if operator not in ("in", "any"):
            return NotImplemented
        if operator == "any":
            operator = "in"
            if isinstance(value, Domain):
                value = self.env["stock.move.line"]._search(value)

        if isinstance(value, Iterable) and not isinstance(value, str):
            value = list(value)
        if isinstance(value, list) and value == [False]:
            return [("id", "not in", self._packages_of_move_lines(Domain.TRUE))]
        return [
            ("id", "in", self._packages_of_move_lines(Domain("id", operator, value)))
        ]

    def _search_owner_id(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return Domain("contained_quant_ids.owner_id", operator, value)

    def _search_picking_ids(self, operator, value):
        if operator != "in":
            return NotImplemented
        return [
            (
                "id",
                "in",
                self._packages_of_move_lines(Domain("picking_id", "in", value)),
            )
        ]

    def action_add_to_picking(self):
        picking = self.env["stock.picking"].browse(self.env.context.get("picking_id"))
        if picking and self:
            picking.action_add_entire_packs(self.ids)

    def action_put_in_pack(
        self, *, package_id=False, package_type_id=False, package_name=False
    ):
        action = self._pre_put_in_pack_hook(
            package_id,
            package_type_id,
            package_name,
            self.env.context.get("from_package_wizard"),
        )
        if action:
            return action

        if package_id:
            package = self.env["stock.package"].browse(package_id)
        else:
            package = self.env["stock.package"].create(
                {
                    "package_type_id": package_type_id,
                    "name": package_name,
                }
            )
        previous_dest_packages = (
            self.env["stock.package"].browse(self._get_all_package_dest_ids()) - self
        )
        self.package_dest_id = package
        if packs_to_clear := previous_dest_packages.filtered(
            lambda p: not p.move_line_ids
        ):
            packs_to_clear.package_dest_id = False

        package.move_line_ids._apply_putaway_strategy()
        return package._post_put_in_pack_hook()

    def action_remove_package(self):
        all_package_dest_ids = self._get_all_package_dest_ids()
        all_move_line_ids = set(self.move_line_ids.ids)
        move_line_ids_to_unlink = set()
        related_move_ids = set()
        move_line_ids_to_update = set()
        picking_ids = self.env.context.get("picking_ids")
        for line in self.move_line_ids:
            if picking_ids and line.picking_id.id not in picking_ids:
                continue
            if line.result_package_id.id in self.ids:
                if line.is_entire_pack:
                    move_line_ids_to_unlink.add(line.id)
                    related_move_ids.add(line.move_id.id)
                else:
                    move_line_ids_to_update.add(line.id)

        self.env["stock.move.line"].browse(move_line_ids_to_unlink).unlink()
        self.env["stock.move.line"].browse(move_line_ids_to_update).write(
            {"result_package_id": False}
        )
        self.env["stock.move"].search_fetch(
            [
                ("id", "in", related_move_ids),
                ("product_uom_qty", "=", 0),
                ("move_line_ids", "=", False),
            ],
            field_names=["id"],
        ).unlink()

        self.child_package_dest_ids.package_dest_id = False
        self.package_dest_id = False

        self.env["stock.package"].search_fetch(
            [("id", "in", all_package_dest_ids), ("move_line_ids", "=", False)],
            field_names=["id"],
        ).write({"package_dest_id": False})

        self.env["stock.move.line"].browse(
            all_move_line_ids - move_line_ids_to_unlink
        )._apply_putaway_strategy()
        return True

    def action_view_picking(self):
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_picking_tree_all"
        )
        move_lines = self.env["stock.move.line"].search_fetch(
            domain=Domain("result_package_id", "in", self.ids)
            | Domain("package_id", "in", self.ids),
            field_names=["picking_id"],
        )
        action["domain"] = [("id", "in", move_lines.picking_id.ids)]
        return action

    def _apply_dest_to_package(self, processed_package_ids=None):
        if processed_package_ids is None:
            processed_package_ids = set()
        packages_todo = self.filtered(lambda p: p.id not in processed_package_ids)
        packs_by_container = packages_todo.grouped("package_dest_id")
        for container_package, packages in packs_by_container.items():
            if not container_package:
                packages.write({"parent_package_id": False})
                processed_package_ids.update(packages.ids)
                continue
            new_location = packages.location_id
            if len(new_location) > 1:
                raise UserError(
                    _(
                        "Packages %(duplicate_names)s are moved to different locations while being in the same container %(container_name)s.",
                        duplicate_names=packages.mapped("name"),
                        container_name=container_package.name,
                    )
                )
            contained_quants = container_package.contained_quant_ids.filtered(
                lambda q: (
                    not float_is_zero(
                        q.quantity, precision_rounding=q.product_uom_id.rounding
                    )
                )
            )
            if contained_quants and contained_quants.location_id != new_location:
                old_location = contained_quants.location_id - new_location
                raise UserError(
                    _(
                        "Can't move a container having packages in another location (%(old_location)s) to a different location (%(new_location)s).",
                        old_location=old_location.display_name,
                        new_location=new_location.display_name,
                    )
                )
            packages.write(
                {
                    "parent_package_id": container_package.id,
                    "package_dest_id": False,
                }
            )
            processed_package_ids.update(packages.ids)
        if (
            packages_todo.parent_package_id.package_dest_id
            or packages_todo.parent_package_id.parent_package_id
        ):
            packages_todo.parent_package_id._apply_dest_to_package(
                processed_package_ids
            )

    def _apply_package_dest_for_entire_packs(self, allowed_package_ids=None):
        for container, packages in self.grouped("parent_package_id").items():
            if (
                container.child_package_ids == packages
                and container.package_type_id.package_use != "reusable"
            ):
                if allowed_package_ids and container.id not in allowed_package_ids:
                    continue
                packages.package_dest_id = container
        if self.package_dest_id:
            self.package_dest_id._apply_package_dest_for_entire_packs(
                allowed_package_ids
            )

    def _get_weight(self, picking_id=False):
        if picking_id:
            return {
                package: weight
                for (package, __), weight in self._get_weight_by_picking(
                    [picking_id]
                ).items()
            }
        res = {}
        for package in self:
            weight = sum(
                contained.package_type_id.base_weight
                for contained in package | package.all_children_package_ids
            )
            weight += sum(
                quant.quantity * quant.product_id.weight
                for quant in package.contained_quant_ids
            )
            res[package] = weight
        return res

    def _get_weight_by_picking(self, picking_ids):
        picking_ids = list(picking_ids)
        package_weights = defaultdict(float)
        children_by_dest_pack, all_pack_ids = self._get_all_children_package_dest_ids()
        base_weight_per_package_group = self.env["stock.package"]._read_group(
            domain=[("id", "in", all_pack_ids)],
            groupby=["id", "package_type_id.base_weight"],
        )
        base_weight_per_package = {
            pack.id: weight for pack, weight in base_weight_per_package_group
        }

        res_groups = self.env["stock.move.line"]._read_group(
            [
                ("result_package_id", "in", all_pack_ids),
                ("product_id", "!=", False),
                ("picking_id", "in", picking_ids),
            ],
            ["picking_id", "result_package_id", "product_id", "product_uom_id"],
            ["quantity:sum"],
        )
        for picking, result_package, product, product_uom_id, quantity in res_groups:
            package_weights[(picking.id, result_package.id)] += (
                product_uom_id._compute_quantity(quantity, product.uom_id)
                * product.weight
            )

        res = {}
        for package in self:
            base_weight = package.package_type_id.base_weight or 0.0
            for picking_id in picking_ids:
                weight = base_weight + package_weights[(picking_id, package.id)]
                for child_id in children_by_dest_pack.get(package, []):
                    weight += (
                        base_weight_per_package.get(child_id, 0)
                        + package_weights[(picking_id, child_id)]
                    )
                res[(package, picking_id)] = weight
        return res

    def _get_all_children_package_dest_ids(self):
        def fetch_next_children(packages):
            if packages.child_package_dest_ids:
                return set(packages.ids) | fetch_next_children(
                    packages.child_package_dest_ids
                )
            else:
                return set(packages.ids)

        all_children_ids = set(self.ids)
        all_children_by_pack = defaultdict(list)
        all_children_ids = set(self.ids)
        for package in self:
            descendants = self._walk_dest_tree(
                package.child_package_dest_ids, "child_package_dest_ids"
            )
            if descendants:
                all_children_by_pack[package] = list(descendants)
                all_children_ids.update(descendants)

        return all_children_by_pack, all_children_ids

    @staticmethod
    def _walk_dest_tree(start, link_field):
        seen = set()
        frontier = start
        while frontier:
            frontier = frontier.browse(set(frontier.ids) - seen)
            seen.update(frontier.ids)
            frontier = frontier[link_field]
        return seen

    def _clear_orphaned_package_dests(self):
        self.filtered(
            lambda package: package.package_dest_id and not package.picking_ids
        ).package_dest_id = False

    def _get_all_package_dest_ids(self):
        return list(self._walk_dest_tree(self, "package_dest_id"))

    def unpack(self):
        self.child_package_ids.parent_package_id = False
        quants = self.quant_ids
        if quants:
            quants.move_quants(message=_("Quantities unpacked"), unpack=True)
            quants._quant_tasks()

    def _pre_put_in_pack_hook(
        self,
        package_id=False,
        package_type_id=False,
        package_name=False,
        from_package_wizard=False,
    ):
        if self.move_line_ids._should_display_put_in_pack_wizard(
            package_id, package_type_id, package_name, from_package_wizard
        ):
            action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
                "stock.action_put_in_pack_wizard"
            )
            action["context"] = {
                **eval_action_context(action.get("context"), self.env),
                "default_package_ids": self.ids,
                "default_location_dest_id": self.location_dest_id[:1].id,
            }
            return action
        return False

    def _post_put_in_pack_hook(self):
        self.ensure_one()
        return self

    def _check_move_lines_map_quant(self, move_lines):
        precision_digits = self.env["decimal.precision"].get_precision("Product Unit")

        def _keys_groupby(record):
            return record.product_id, record.lot_id

        if not move_lines:
            return True
        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")

        def by_product_and_lot(records, quantity_field):
            return {
                key: sum(group.mapped(quantity_field))
                for key, group in records.grouped(
                    lambda record: (record.product_id, record.lot_id)
                ).items()
            }

        quantities = by_product_and_lot(self.contained_quant_ids, "quantity")
        operations = by_product_and_lot(move_lines, "quantity_product_uom")

        return all(
            float_is_zero(
                quantities.get(key, 0) - operations.get(key, 0),
                precision_digits=precision_digits,
            )
            for key in quantities.keys() | operations.keys()
        )

    def _has_issues(self):
        self.ensure_one()
        return len(self.move_line_ids.location_dest_id) > 1
