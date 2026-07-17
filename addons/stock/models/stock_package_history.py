from odoo import fields, models


class StockPackageHistory(models.Model):
    _name = "stock.package.history"
    _description = "Stock Package History"
    _check_company_auto = True

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Origin Location",
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination Location",
    )
    move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="package_history_id",
        string="Move Lines",
        required=True,
    )
    package_id = fields.Many2one(
        comodel_name="stock.package",
        string="Package",
        required=True,
        ondelete="cascade",
    )
    package_name = fields.Char(string="Package Name", required=True)
    package_type_id = fields.Many2one(
        related="package_id.package_type_id",
        comodel_name="stock.package.type",
    )
    parent_orig_id = fields.Many2one(
        comodel_name="stock.package",
        string="Origin Container",
    )
    parent_orig_name = fields.Char(string="Origin Container Name")
    parent_dest_id = fields.Many2one(
        comodel_name="stock.package",
        string="Destination Container",
    )
    parent_dest_name = fields.Char(string="Destination Container Name")
    outermost_dest_id = fields.Many2one(
        comodel_name="stock.package",
        string="Outermost Destination Container",
    )
    picking_ids = fields.Many2many(
        comodel_name="stock.picking",
        string="Transfers",
    )

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_view_package(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "stock.package",
            "res_id": self.package_id.id,
        }

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_complete_dest_name_except_outermost(self):
        """Return the frozen destination chain minus its outermost container.

        ``package_name`` snapshots the package's *destination* chain
        (``dest_complete_name``) at validation time -- taken before
        ``_apply_dest_to_package`` re-parents the packages and clears
        ``package_dest_id`` -- so dropping the first (outermost) segment yields
        the containers the package sits in below the outermost one. When the
        direct destination container *is* the outermost, that is just the
        package's own (frozen) name.
        """
        self.ensure_one()
        if not self.parent_dest_id:
            return ""
        return " > ".join(self.package_name.split(" > ")[1:])
