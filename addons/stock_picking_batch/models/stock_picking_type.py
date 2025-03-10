# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"


    wave_category_ids = fields.Many2many(
        comodel_name="product.category",
        string="Wave Product Categories",
        help="Categories to consider when grouping waves.",
    )
    wave_location_ids = fields.Many2many(
        comodel_name="stock.location",
        string="Wave Locations",
        domain="[('usage', '=', 'internal')]",
        help="Locations to consider when grouping waves.",
    )
    count_picking_batch = fields.Integer(
        compute="_compute_picking_count",
    )
    count_picking_wave = fields.Integer(
        compute="_compute_picking_count",
    )
    auto_batch = fields.Boolean(
        string="Automatic Batches",
        help="Automatically put pickings into batches as they are confirmed when possible.",
    )
    batch_group_by_partner = fields.Boolean(
        string="Contact",
        help="Automatically group batches by contacts."
    )
    batch_group_by_destination = fields.Boolean(
        string="Destination Country",
        help="Automatically group batches by destination country.",
    )
    batch_group_by_src_loc = fields.Boolean(
        string="Group by Source Location",
        help="Automatically group batches by their source location.",
    )
    batch_group_by_dest_loc = fields.Boolean(
        string="Group by Destination Location",
        help="Automatically group batches by their destination location.",
    )
    wave_group_by_product = fields.Boolean(
        string="Product",
        help="Split transfers by product then group transfers that have the same product.",
    )
    wave_group_by_category = fields.Boolean(
        string="Product Category",
        help="Split transfers by product category, then group transfers that have the same product category.",
    )
    wave_group_by_location = fields.Boolean(
        string="Location",
        help="Split transfers by defined locations, then group transfers with the same location.",
    )
    batch_auto_confirm = fields.Boolean("Auto-confirm", default=True)
    batch_max_lines = fields.Integer(
        string="Maximum lines",
        help="A transfer will not be automatically added to batches that will exceed this number of lines "
             "if the transfer is added to it.\n"
             "Leave this value as '0' if no line limit.",
    )
    batch_max_pickings = fields.Integer(
        string="Maximum transfers",
        help="A transfer will not be automatically added to batches that will exceed this number of "
             "transfers.\n Leave this value as '0' if no transfer limit.",
    )
    batch_properties_definition = fields.PropertiesDefinition("Batch Properties")


    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------

    @api.constrains(lambda self: self._get_batch_group_by_keys() + ["auto_batch"])
    def _validate_auto_batch_group_by(self):
        group_by_keys = self._get_batch_and_wave_group_by_keys()
        for picking_type in self:
            if not picking_type.auto_batch:
                continue

            if not any(picking_type[key] for key in group_by_keys):
                raise ValidationError(_(
                    "If the Automatic Batches feature is enabled, at least one 'Group by' option must be selected."
                ))


    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    def _compute_picking_count(self):
        super()._compute_picking_count()
        data = self.env["stock.picking.batch"]._read_group(
            [
                ("state", "not in", ("done", "cancel")),
                ("picking_type_id", "in", self.ids),
            ],
            ["picking_type_id", "is_wave"],
            ["__count"],
        )
        count = {
            (picking_type.id, is_wave): count for picking_type, is_wave, count in data
        }
        for record in self:
            record.count_picking_wave = count.get((record.id, True), 0)
            record.count_picking_batch = count.get((record.id, False), 0)


    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------

    def action_batch(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock_picking_batch.stock_picking_batch_action"
        )
        if self.env.context.get("view_mode"):
            del action["mobile_view_mode"]
            del action["views"]
            action["view_mode"] = self.env.context["view_mode"]
        return action


    # -------------------------------------------------------------------------
    # 
    # -------------------------------------------------------------------------

    @api.model
    def _get_batch_group_by_keys(self):
        return [
            "batch_group_by_partner",
            "batch_group_by_destination",
            "batch_group_by_src_loc",
            "batch_group_by_dest_loc",
        ]

    @api.model
    def _get_wave_group_by_keys(self):
        return [
            "wave_group_by_product",
            "wave_group_by_category",
            "wave_group_by_location",
        ]

    @api.model
    def _get_batch_and_wave_group_by_keys(self):
        return self._get_batch_group_by_keys() + self._get_wave_group_by_keys()

    @api.model
    def _is_auto_batch_grouped(self):
        self.ensure_one()
        return self.auto_batch and any(
            self[key] for key in self._get_batch_group_by_keys()
        )

    @api.model
    def _is_auto_wave_grouped(self):
        self.ensure_one()
        return self.auto_batch and any(
            self[key] for key in self._get_wave_group_by_keys()
        )
