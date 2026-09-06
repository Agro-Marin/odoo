from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartnerAttributeLine(models.Model):
    _name = "res.partner.attribute.line"
    _inherit = "mixin.attribute.line"
    _description = "Partner Attribute Line"
    _order = "attribute_id, id"
    _rec_name = "attribute_id"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        required=True,
        ondelete="cascade",
        index=True,
    )
    attribute_id = fields.Many2one(
        comodel_name="res.partner.attribute",
        required=True,
        ondelete="restrict",
        index=True,
    )
    value_ids = fields.Many2many(
        comodel_name="res.partner.attribute.value",
        relation="res_partner_attribute_line_value_rel",
        column1="line_id",
        column2="value_id",
        string="Values",
        domain="[('attribute_id', '=', attribute_id)]",
    )

    _partner_attribute_uniq = models.Constraint(
        "UNIQUE(partner_id, attribute_id)",
        "This attribute is already set for the partner.",
    )

    _SCORE_TRIGGERS = ("partner_id", "attribute_id", "value_ids", "active")

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.partner_id._update_profile_scores()
        return lines

    def write(self, vals):
        if not any(name in vals for name in self._SCORE_TRIGGERS):
            return super().write(vals)
        partners_before = self.partner_id
        result = super().write(vals)
        (partners_before | self.partner_id)._update_profile_scores()
        return result

    def unlink(self):
        partners = self.partner_id
        result = super().unlink()
        partners._update_profile_scores()
        return result

    @api.constrains("partner_id")
    def _check_commercial_partner(self):
        for line in self:
            partner = line.partner_id
            if partner != partner.commercial_partner_id:
                raise ValidationError(
                    self.env._(
                        "Profile attributes can only be set on the commercial "
                        "entity %(commercial)s, not on its contact %(contact)s.",
                        commercial=partner.commercial_partner_id.display_name,
                        contact=partner.display_name,
                    )
                )
