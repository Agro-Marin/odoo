from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL, check_barcode_encoding, groupby
from odoo.tools.float_utils import float_compare, float_is_zero


class StockQuantPackage(models.Model):
    """Packages containing quants and/or other packages"""

    _name = "stock.quant.package"
    _description = "Packages"
    _order = "name"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    name = fields.Char(
        "Package Reference",
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("stock.quant.package")
        or _("Unknown Pack"),
        copy=False,
        index="trigram",
    )
    package_type_id = fields.Many2one(
        "stock.package.type",
        "Package Type",
        index=True,
    )
    location_id = fields.Many2one(
        "stock.location",
        "Location",
        compute="_compute_package_info",
        store=True,
        readonly=False,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        compute="_compute_package_info",
        store=True,
        readonly=True,
        index=True,
    )
    owner_id = fields.Many2one(
        "res.partner",
        "Owner",
        compute="_compute_owner_id",
        compute_sudo=True,
        readonly=True,
        search="_search_owner",
    )
    pack_date = fields.Date("Pack Date", default=fields.Date.today)
    package_use = fields.Selection(
        [
            ("disposable", "Disposable Box"),
            ("reusable", "Reusable Box"),
        ],
        string="Package Use",
        required=True,
        default="disposable",
        help="""Reusable boxes are used for batch picking and emptied afterwards to be reused. In the barcode application, scanning a reusable box will add the products in this box.
        Disposable boxes aren't reused, when scanning a disposable box in the barcode application, the contained products are added to the transfer.""",
    )
    quant_ids = fields.One2many(
        "stock.quant",
        "package_id",
        "Bulk Content",
        readonly=True,
        domain=["|", ("quantity", "!=", 0), ("reserved_quantity", "!=", 0)],
    )
    shipping_weight = fields.Float(
        string="Shipping Weight",
        help="Total weight of the package.",
    )
    valid_sscc = fields.Boolean(
        "Package name is valid SSCC",
        compute="_compute_valid_sscc",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    def write(self, vals):
        if "location_id" in vals:
            if not vals["location_id"]:
                raise UserError(_("Cannot remove the location of a non empty package"))

            if any(not pack.quant_ids for pack in self):
                raise UserError(_("Cannot move an empty package"))

            # create a move from the old location to new location
            location_dest_id = self.env["stock.location"].browse(vals["location_id"])
            quant_to_move = self.quant_ids.filtered(lambda q: q.quantity > 0)
            quant_to_move.move_quants(
                location_dest_id, message=_("Package manually relocated")
            )
        return super().write(vals)

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("quant_ids.location_id", "quant_ids.company_id")
    def _compute_package_info(self):
        for package in self:
            package.location_id = False
            package.company_id = False
            quants = package.quant_ids.filtered(
                lambda q: float_compare(
                    q.quantity, 0, precision_rounding=q.product_uom_id.rounding
                )
                > 0
            )
            if quants:
                package.location_id = quants[0].location_id
                if all(q.company_id == quants[0].company_id for q in package.quant_ids):
                    package.company_id = quants[0].company_id

    @api.depends("quant_ids.owner_id")
    def _compute_owner_id(self):
        for package in self:
            package.owner_id = False
            if package.quant_ids and all(
                q.owner_id == package.quant_ids[0].owner_id for q in package.quant_ids
            ):
                package.owner_id = package.quant_ids[0].owner_id

    @api.depends("name")
    def _compute_valid_sscc(self):
        self.valid_sscc = False
        for package in self:
            if package.name:
                package.valid_sscc = check_barcode_encoding(package.name, "sscc")

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_owner(self, operator, value):
        if value:
            packs = self.search([("quant_ids.owner_id", operator, value)])
        else:
            packs = self.search([("quant_ids", operator, value)])
        if packs:
            return [("id", "in", packs.ids)]
        else:
            return [("id", "=", False)]

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

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
    # HELPERS
    # ------------------------------------------------------------

    def unpack(self):
        self.quant_ids.move_quants(message=_("Quantities unpacked"), unpack=True)
        # Quant clean-up, mostly to avoid multiple quants of the same product. For example, unpack
        # 2 packages of 50, then reserve 100 => a quant of -50 is created at transfer validation.
        self.quant_ids._quant_tasks()

    def _check_move_lines_map_quant(self, move_lines):
        """This method checks that all product (quants) of self (package) are well present in the `move_line_ids`."""
        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")

        def _keys_groupby(record):
            return record.product_id, record.lot_id

        grouped_quants = {}
        for k, g in groupby(self.quant_ids, key=_keys_groupby):
            grouped_quants[k] = sum(
                self.env["stock.quant"].concat(*g).mapped("quantity")
            )

        grouped_ops = {}
        for k, g in groupby(move_lines, key=_keys_groupby):
            grouped_ops[k] = sum(
                self.env["stock.move.line"].concat(*g).mapped("quantity")
            )

        if any(
            not float_is_zero(
                grouped_quants.get(key, 0) - grouped_ops.get(key, 0),
                precision_digits=precision_digits,
            )
            for key in grouped_quants
        ) or any(
            not float_is_zero(
                grouped_ops.get(key, 0) - grouped_quants.get(key, 0),
                precision_digits=precision_digits,
            )
            for key in grouped_ops
        ):
            return False
        return True

    def _get_weight(self, picking_id=False):
        res = {}
        if picking_id:
            package_weights = defaultdict(float)
            res_groups = self.env["stock.move.line"]._read_group(
                [
                    ("result_package_id", "in", self.ids),
                    ("product_id", "!=", False),
                    ("picking_id", "=", picking_id),
                ],
                ["result_package_id", "product_id", "product_uom_id", "quantity"],
                ["__count"],
            )
            for result_package, product, product_uom, quantity, count in res_groups:
                package_weights[result_package.id] += (
                    count
                    * product_uom._compute_quantity(quantity, product.uom_id)
                    * product.weight
                )
        for package in self:
            weight = package.package_type_id.base_weight or 0.0
            if picking_id:
                res[package] = weight + package_weights[package.id]
            else:
                for quant in package.quant_ids:
                    weight += quant.quantity * quant.product_id.weight
                res[package] = weight
        return res
