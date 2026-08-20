from odoo import fields, models

from odoo.addons.base.models.mixin_catalog import name_uniq_index


class SlideTag(models.Model):
    """Tag to search slides across channels."""

    _name = "slide.tag"
    _description = "Slide Tag"

    name = fields.Char("Name", required=True, translate=True)

    _name_src_uniq = name_uniq_index(
        message="A tag must be unique!",
    )
