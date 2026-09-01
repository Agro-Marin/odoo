from odoo import fields, models

from .mixin_catalog import no_name_uniq_index


class ResPartnerTag(models.Model):
    _name = "res.partner.tag"
    _description = "Partner Tag"
    _inherit = ["mixin.tag.nested"]

    # A partner tag is a label, not a catalog entry: base's own hierarchy and
    # translation suites use this model as their fixture and create duplicate
    # names on purpose, and users have always been able to. Adopt the mixin for
    # the shared tree behaviour and the stable code, decline its name
    # uniqueness -- the same call product.attribute makes.
    _name_src_uniq = no_name_uniq_index()

    parent_id: ResPartnerTag = fields.Many2one(
        "res.partner.tag",
        string="Parent Tag",
        index=True,
        ondelete="cascade",
    )
    child_ids: ResPartnerTag = fields.One2many(
        "res.partner.tag", "parent_id", string="Child Tags"
    )
    partner_ids = fields.Many2many(
        "res.partner",
        column1="tag_id",
        column2="partner_id",
        string="Partners",
        copy=False,
    )
