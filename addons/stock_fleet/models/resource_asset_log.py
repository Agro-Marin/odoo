from odoo import fields, models


class ResourceAssetLog(models.Model):
    _inherit = "resource.asset.log"

    source = fields.Selection(
        selection_add=[("delivery", "Trip")],
        ondelete={"delivery": "set default"},
    )
    picking_batch_id = fields.Many2one(
        comodel_name="stock.picking.batch",
        string="Trip",
        index="btree_not_null",
        ondelete="set null",
        help="Trip whose return odometer this reading is.",
    )

    _picking_batch_uniq = models.Constraint(
        "UNIQUE(picking_batch_id)",
        "This trip has already recorded its return odometer.",
    )
