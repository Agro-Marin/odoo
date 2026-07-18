import json
from ast import literal_eval
from collections import defaultdict
from collections.abc import Iterable

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.barcode import check_barcode_encoding
from odoo.libs.numbers.float_utils import float_is_zero
from odoo.tools import format_list, groupby


class StockPackage(models.Model):
    _name = "stock.package"
    _description = "Package"
    _order = "name, id"
    _parent_name = "parent_package_id"
    _parent_store = True
    _rec_name = "complete_name"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

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
        search="_search_owner",
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
        search="_search_outermost_package_id",
        recursive=True,
    )
    child_package_dest_ids = fields.One2many(
        comodel_name="stock.package",
        inverse_name="package_dest_id",
        string="Assigned Contained Packages",
    )
    move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        compute="_compute_move_line_ids",
        search="_search_move_line_ids",
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
        help="Total weight of the package.",
    )
    valid_sscc = fields.Boolean(
        string="Package name is valid SSCC",
        compute="_compute_valid_sscc",
    )
    pack_date = fields.Date(string="Pack Date", default=fields.Date.today)
    parent_path = fields.Char(index=True)
    json_popover = fields.Char(
        string="JSON data for popover widget",
        compute="_compute_json_popover",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("complete_name"):
                vals["name"] = vals["complete_name"]
                del vals["complete_name"]
            if not vals.get("name"):
                package_type = self.env["stock.package.type"].browse(
                    vals.get("package_type_id")
                )
                vals["name"] = package_type._get_next_name_by_sequence()

        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals and not vals.get("name"):
            # Regenerate the name from the sequence if it was emptied. The type may
            # come from vals (same for the whole batch) or fall back to each
            # package's own type, so resolve it per record.
            for package in self:
                package_type = self.env["stock.package.type"].browse(
                    vals.get("package_type_id", package.package_type_id.id)
                )
                package.name = package_type._get_next_name_by_sequence()
            del vals["name"]
        if "location_id" in vals:
            # Per-record guards: a batch mixing empty and non-empty packages must
            # neither clear the location of a non-empty one nor move an empty one.
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
                    lambda q: q.quantity > 0
                )
                quant_to_move.move_quants(
                    location_dest_id,
                    message=_("Package manually relocated"),
                    up_to_parent_packages=self,
                )
                # Negative quants (pending accounting, e.g. an outbound
                # validated before its inbound) must relocate too, or the
                # package stays split across the old and new locations and the
                # negative never nets against future receipts at the new one.
                # Moving a -N quant from OLD to NEW means moving N units
                # NEW -> OLD within the same package: it nets the OLD quant to
                # zero and recreates the -N at NEW.
                negative_quants = self.contained_quant_ids.filtered(
                    lambda q: q.quantity < 0
                )
                if negative_quants:
                    message = _("Package manually relocated")
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
        if vals.get("package_dest_id"):
            # Guard against a cycle in the package_dest_id chain; parent_path
            # can't be used here since it only tracks parent_package_id.
            current_children_dest_ids = self._get_all_children_package_dest_ids()[1]
            if vals["package_dest_id"] in current_children_dest_ids:
                raise ValidationError(
                    _(
                        "A package can't have one of its contained packages as destination container."
                    ),
                )

        return super().write(vals)

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

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
                package.env.context.get("formatted_display_name")
                and package.package_type_id
                and package.package_type_id.packaging_length
                and package.package_type_id.width
                and package.package_type_id.height
            ):
                package.display_name = f"{display_name}\t--{package.package_type_id.packaging_length} x {package.package_type_id.width} x {package.package_type_id.height}--"
            else:
                package.display_name = display_name

    @api.depends("name", "parent_package_id.complete_name")
    def _compute_complete_name(self):
        for package in self:
            if package.parent_package_id:
                package.complete_name = "%s > %s" % (
                    package.parent_package_id.complete_name,
                    package.name,
                )
            else:
                package.complete_name = package.name

    @api.depends("name", "package_dest_id.dest_complete_name")
    def _compute_dest_complete_name(self):
        for package in self:
            if package.package_dest_id:
                package.dest_complete_name = "%s > %s" % (
                    package.package_dest_id.dest_complete_name,
                    package.name,
                )
            else:
                package.dest_complete_name = package.name

    @api.depends("quant_ids", "all_children_package_ids.quant_ids")
    def _compute_contained_quant_ids(self):
        for package in self:
            package.contained_quant_ids = (
                package.quant_ids | package.all_children_package_ids.quant_ids
            )

    @api.depends("contained_quant_ids")
    def _compute_content_description(self):
        def format_content(qty, uom_name, product_name, display_uom):
            quantity = str(int(qty) if qty == int(qty) else qty)
            return " ".join(
                [quantity, uom_name, product_name]
                if display_uom
                else [quantity, product_name]
            )

        display_uom = self.env.user.has_group("uom.group_uom")
        for package in self:
            package_content = package.contained_quant_ids.grouped(
                lambda q: (q.product_uom_id, q.product_id)
            )
            package_content = [
                (uom.name, product.display_name, sum(quants.mapped("quantity")))
                for ((uom, product), quants) in package_content.items()
            ]
            package.content_description = format_list(
                self.env,
                [
                    format_content(qty, uom_name, product_name, display_uom)
                    for (uom_name, product_name, qty) in package_content
                ],
            )

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

    @api.depends("move_line_ids")
    def _compute_location_dest_id(self):
        for package in self:
            package.location_dest_id = (
                package.move_line_ids.location_dest_id[:1] or False
            )

    @api.depends("location_id", "child_package_dest_ids")
    def _compute_move_line_ids(self):
        # location_id isn't used below but stays in @api.depends to force a
        # recompute of move_line_ids whenever the package changes location.
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
        # An in-place quant update (e.g. an inventory adjustment zeroing a
        # quantity, or a relocation rewriting location_id) changes the outcome
        # without changing the quant_ids set, so it must trigger too.
        "quant_ids.quantity",
        "quant_ids.location_id",
        "quant_ids.company_id",
    )
    def _compute_package_info(self):
        # Location and company are only meaningful when unambiguous: a package
        # whose positive quants (or child packages) span several locations or
        # companies is in an inconsistent state, and silently electing the first
        # quant's value would hide it (and make the result depend on quant
        # ordering). Mirror the homogeneity rule already applied to the company.
        for package in self:
            package.location_id = False
            package.company_id = False
            # Homogeneity only over the positive quants: a stale zero-quantity
            # quant left in another location/company must not blank the values.
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
                # Location-less children (e.g. empty packages) don't make the
                # located ones ambiguous, so only distinct truthy values count.
                locations = package.child_package_ids.location_id
                if len(locations) == 1:
                    package.location_id = locations
                companies = package.child_package_ids.company_id
                if len(companies) == 1 and all(
                    p.company_id for p in package.child_package_ids
                ):
                    package.company_id = companies

    @api.depends("child_package_dest_ids")
    def _compute_picking_ids(self):
        children_by_dest_pack, all_pack_ids = self._get_all_children_package_dest_ids()
        groups = self.env["stock.move.line"]._read_group(
            domain=[
                ("state", "not in", ["done", "cancel"]),
                ("result_package_id", "in", all_pack_ids),
            ],
            groupby=["result_package_id"],
            aggregates=["picking_id:array_agg"],
        )
        pickings_by_package = {
            package.id: picking_ids for package, picking_ids in groups
        }

        for package in self:
            picking_ids = {
                picking_id
                for child_id in children_by_dest_pack[package]
                for picking_id in pickings_by_package.get(child_id, [])
            }
            picking_ids.update(pickings_by_package.get(package.id, []))
            package.picking_ids = [Command.set(list(picking_ids))]

    @api.depends("contained_quant_ids.owner_id")
    def _compute_owner_id(self):
        # Aggregate over the whole content (own quants plus nested packages'):
        # a container whose goods all belong to one owner through its children
        # must expose that owner too.
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
        self.valid_sscc = False
        for package in self:
            if package.name:
                package.valid_sscc = check_barcode_encoding(package.name, "sscc")

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_all_children_package_ids(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            # Let the ORM derive the negation from the positive domain: wrapping a
            # negative operator's matches with parent_of composes wrongly (a package
            # that DOES contain the target would match "not in", because its child
            # matched the negated inner search).
            return NotImplemented
        packages = self.search_fetch(
            domain=[("id", operator, value)], field_names=["id"]
        )
        return [("id", "parent_of", packages.ids)]

    def _search_contained_quant_ids(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        packages = self.search([("quant_ids", operator, value)])
        if packages:
            return [("id", "parent_of", packages.ids)]
        else:
            return [("id", "=", False)]

    def _search_location_dest_id(self, operator, value):
        if operator not in ["in", "not in"]:
            return NotImplemented

        move_lines = self.env["stock.move.line"].search_fetch(
            domain=[
                ("state", "not in", ["done", "cancel"]),
                ("location_dest_id", operator, value),
            ],
            field_names=["result_package_id"],
        )
        all_package_ids = move_lines.result_package_id._get_all_package_dest_ids()

        return [("id", "in", all_package_ids)]

    def _search_move_line_ids(self, operator, value):
        if operator not in ("in", "any"):
            return NotImplemented
        if operator == "any":
            operator = "in"
            if isinstance(value, Domain):
                value = self.env["stock.move.line"]._search(value)

        if isinstance(value, Iterable) and not isinstance(value, str):
            # Materialize one-shot iterables (e.g. generators): `value` is
            # inspected below and then reused inside the domain.
            value = list(value)
        domain = Domain("state", "not in", ["done", "cancel"])
        pack_operator = "in"
        if isinstance(value, list) and value == [False]:
            # ('move_line_ids', '=', False): not assigned to any ongoing picking
            pack_operator = "not in"
        else:
            domain &= Domain("id", operator, value)
        move_lines = self.env["stock.move.line"].search_fetch(
            domain=domain, field_names=["result_package_id"]
        )
        all_package_ids = move_lines.result_package_id._get_all_package_dest_ids()

        return [("id", pack_operator, all_package_ids)]

    def _search_outermost_package_id(self, operator, value):
        if operator not in ["in", "not in"]:
            return NotImplemented

        packages = self.env["stock.package"].search_fetch(
            domain=[("package_dest_id", operator, value)],
            field_names=["child_package_dest_ids"],
        )
        __, all_children_ids = packages._get_all_children_package_dest_ids()
        return [("id", "in", all_children_ids)]

    def _search_owner(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return Domain("quant_ids.owner_id", operator, value)

    def _search_picking_ids(self, operator, value):
        if operator not in ["in", "not in"]:
            return NotImplemented

        move_lines = self.env["stock.move.line"].search_fetch(
            domain=[
                ("state", "not in", ["done", "cancel"]),
                ("picking_id", operator, value),
            ],
            field_names=["result_package_id"],
        )
        all_package_ids = move_lines.result_package_id._get_all_package_dest_ids()

        return [("id", "in", all_package_ids)]

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

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
        previous_dest_packages = self.env["stock.package"].browse(
            self._get_all_package_dest_ids()
        )
        self.package_dest_id = package
        if packs_to_clear := previous_dest_packages.filtered(
            lambda p: not p.move_line_ids
        ):
            # No move line points to these former dest packages now that the
            # container changed, so they're irrelevant: free them.
            packs_to_clear.package_dest_id = False

        # The uppermost package changed, so new putaway rules may apply.
        package.move_line_ids._apply_putaway_strategy()
        return package._post_put_in_pack_hook()

    def action_remove_package(self):
        """Removes all packages in self from the destination container tree.
        For move lines directly linked to a package (through result_package_id):
        - If the entire package is moved, remove the move lines entirely from the picking.
        - Otherwise, just unset the package as the line's destination package.
        """
        all_package_dest_ids = self._get_all_package_dest_ids()
        all_move_line_ids = set(self.move_line_ids.ids)
        move_line_ids_to_unlink = set()
        related_move_ids = set()
        move_line_ids_to_update = set()
        for line in self.move_line_ids:
            picking_ids = self.env.context.get("picking_ids")
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
        # Unlink moves with no initial demand and no remaining move lines.
        self.env["stock.move"].search_fetch(
            [
                ("id", "in", related_move_ids),
                ("product_uom_qty", "=", 0),
                ("move_line_ids", "=", False),
            ],
            field_names=["id"],
        ).unlink()

        # If packages in self are dest containers of others, clear that too.
        self.child_package_dest_ids.package_dest_id = False
        self.package_dest_id = False

        # Parent packages now isolated from bottom-level packages: clear their
        # destination container too.
        self.env["stock.package"].search_fetch(
            [("id", "in", all_package_dest_ids), ("move_line_ids", "=", False)],
            field_names=["id"],
        ).write({"package_dest_id": False})

        # If outermost packages were changed, different putaway rules may apply.
        self.env["stock.move.line"].browse(
            all_move_line_ids - move_line_ids_to_unlink
        )._apply_putaway_strategy()
        return True

    def action_view_picking(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_picking_tree_all"
        )
        domain = [
            "|",
            ("result_package_id", "in", self.ids),
            ("package_id", "in", self.ids),
        ]
        pickings = self.env["stock.move.line"].search(domain).mapped("picking_id")
        action["domain"] = [("id", "in", pickings.ids)]
        return action

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _apply_dest_to_package(self, processed_package_ids=None):
        """Move packages into their ``package_dest_id`` container (or detach them
        if none), ensuring the container's quants aren't split across locations.
        """
        packages_todo = self
        if processed_package_ids:
            packages_todo = packages_todo.filtered(
                lambda p: p.id not in processed_package_ids
            )
        else:
            processed_package_ids = set()
        packs_by_container = packages_todo.grouped("package_dest_id")
        for container_package, packages in packs_by_container.items():
            if not container_package:
                # If package has no future container package, needs to be removed from its current one.
                packages.write({"parent_package_id": False})
                processed_package_ids.update(packages.ids)
                continue
            # At this point, the packages were already moved so we need to check their current position.
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
        # First level applied; check whether the next level needs it too.
        if (
            packages_todo.parent_package_id.package_dest_id
            or packages_todo.parent_package_id.parent_package_id
        ):
            packages_todo.parent_package_id._apply_dest_to_package(
                processed_package_ids
            )

    def _apply_package_dest_for_entire_packs(self, allowed_package_ids=None):
        """When a package is added to a picking and its whole container is added
        too, treat the container as added — unless it's a reusable package.
        """
        for container, packages in self.grouped("parent_package_id").items():
            if (
                container.child_package_ids == packages
                and container.package_type_id.package_use != "reusable"
            ):
                if allowed_package_ids and container.id not in allowed_package_ids:
                    continue
                packages.package_dest_id = container
        if self.package_dest_id:
            # One level added: check whether the upper container is fully contained too.
            self.package_dest_id._apply_package_dest_for_entire_packs(
                allowed_package_ids
            )

    def _get_weight(self, picking_id=False):
        res = {}
        if picking_id:
            return {
                package: weight
                for (package, __), weight in self._get_weight_by_picking(
                    [picking_id]
                ).items()
            }
        for package in self:
            weight = package.package_type_id.base_weight or 0.0
            # Add the base_weight of every nested package, including ones that
            # only contain other packages (no quants of their own to weigh).
            weight += sum(
                package.all_children_package_ids.mapped(
                    lambda p: p.package_type_id.base_weight,
                ),
            )
            for quant in package.contained_quant_ids:
                weight += quant.quantity * quant.product_id.weight
            res[package] = weight
        return res

    def _get_weight_by_picking(self, picking_ids):
        """Weight of each package in ``self`` restricted to each given picking's
        own move lines, including the current dest children of the package.

        Batched over pickings: the recursive dest-children walk and the move-line
        aggregation run once for the whole (packages x pickings) set, so callers
        computing weights for many pickings (e.g. `_compute_shipping_weight` on a
        batch validation) do not pay one walk and two grouped queries per picking.

        :param picking_ids: iterable of `stock.picking` ids.
        :return: dict mapping ``(package, picking_id)`` to its weight.
        """
        picking_ids = list(picking_ids)
        # (picking_id, package_id) -> weight of the picking's own product content.
        package_weights = defaultdict(float)
        # For an ongoing picking, also count the weight of current dest children.
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
        """All descendant packages having a package in self as their
        ``package_dest_id``, recursively. Done manually since the model has a
        single _parent field (parent_package_id).

        :returns: tuple(dict mapping each package in self to its dest-descendant
            ids, list of self's ids plus all those descendant ids)
        """

        def fetch_next_children(packages):
            if packages.child_package_dest_ids:
                return set(packages.ids) | fetch_next_children(
                    packages.child_package_dest_ids
                )
            else:
                return set(packages.ids)

        all_children_ids = set(self.ids)
        all_children_by_pack = defaultdict(list)
        for package in self:
            if package.child_package_dest_ids:
                child_ids = list(fetch_next_children(package.child_package_dest_ids))
                all_children_ids.update(child_ids)
                all_children_by_pack[package] = child_ids

        return all_children_by_pack, all_children_ids

    def _get_all_package_dest_ids(self):
        """Self and all its parent destination packages, recursively. Done
        manually since the model has a single _parent field (parent_package_id).

        :returns: list of self's ids and all parent ids.
        """

        def fetch_next_parents(packages):
            if packages.package_dest_id:
                return set(packages.ids) | fetch_next_parents(packages.package_dest_id)
            else:
                return set(packages.ids)

        return list(fetch_next_parents(self))

    def unpack(self):
        """Unpacks quants directly inside the container, and removes contained packages from this package."""
        self.child_package_ids.parent_package_id = False
        if self.quant_ids:
            quants = self.quant_ids
            self.quant_ids.move_quants(
                message=_("Quantities unpacked"),
                unpack=True,
            )
            # Quant clean-up to avoid multiple quants of the same product: e.g.
            # unpack 2 packages of 50, then reserve 100 => a -50 quant at validation.
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
            action = self.env["ir.actions.actions"]._for_xml_id(
                "stock.action_put_in_pack_wizard"
            )
            action["context"] = {
                **literal_eval(action.get("context", "{}")),
                "default_package_ids": self.ids,
                "default_location_dest_id": self.location_dest_id[:1].id,
            }
            return action
        return False

    def _post_put_in_pack_hook(self):
        self.ensure_one()
        return self

    # ------------------------------------------------------------
    # VALIDATION METHODS
    # ------------------------------------------------------------

    def _check_move_lines_map_quant(self, move_lines):
        """Checks that self's contained quants and move_lines carry matching quantities per product and lot."""
        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")

        def _keys_groupby(record):
            return record.product_id, record.lot_id

        if not move_lines:
            return True

        grouped_quants = {}
        for k, g in groupby(self.contained_quant_ids, key=_keys_groupby):
            grouped_quants[k] = sum(
                self.env["stock.quant"].concat(*g).mapped("quantity")
            )

        grouped_ops = {}
        for k, g in groupby(move_lines, key=_keys_groupby):
            grouped_ops[k] = sum(
                self.env["stock.move.line"].concat(*g).mapped("quantity_product_uom"),
            )

        return all(
            float_is_zero(
                grouped_quants.get(key, 0) - grouped_ops.get(key, 0),
                precision_digits=precision_digits,
            )
            for key in grouped_quants
        ) and all(
            float_is_zero(
                grouped_ops.get(key, 0) - grouped_quants.get(key, 0),
                precision_digits=precision_digits,
            )
            for key in grouped_ops
        )

    def _has_issues(self):
        self.ensure_one()
        return len(self.move_line_ids.location_dest_id) > 1
