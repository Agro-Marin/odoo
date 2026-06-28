from odoo import fields, models


class TagTag(models.Model):
    _name = "tag.tag"
    _inherit = ["tag.mixin"]
    _description = "Tag"

    parent_id = fields.Many2one(
        comodel_name="tag.tag",
        string="Parent Tag",
        index=True,
        ondelete="cascade",
    )
    child_ids = fields.One2many(
        comodel_name="tag.tag",
        inverse_name="parent_id",
        string="Child Tags",
    )
