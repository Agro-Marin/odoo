from odoo import fields, models


class SrmTag(models.Model):
    _name = "srm.tag"
    _inherit = ["tag.mixin"]
    _description = "SRM Tag"

    parent_id = fields.Many2one(
        comodel_name="srm.tag",
        string="Parent Tag",
        index=True,
        ondelete="cascade",
    )
    child_ids = fields.One2many(
        comodel_name="srm.tag",
        inverse_name="parent_id",
        string="Child Tags",
    )
    order_ids = fields.Many2many(
        comodel_name="purchase.order",
        relation="purchase_order_tag_rel",
        column1="tag_id",
        column2="order_id",
        string="Purchase Orders",
        copy=False,
    )
