from odoo import fields, models


class CrmLeadScoringFrequency(models.Model):
    _name = "crm.lead.scoring.frequency"
    _description = "Lead Scoring Frequency"

    variable = fields.Char("Variable", index=True)
    value = fields.Char("Value")
    won_count = fields.Float("Won Count", digits=(16, 1))
    lost_count = fields.Float("Lost Count", digits=(16, 1))
    team_id = fields.Many2one("crm.team", "Sales Team", ondelete="cascade")


class CrmLeadScoringFrequencyField(models.Model):
    _name = "crm.lead.scoring.frequency.field"
    _inherit = ["mixin.color"]
    _description = "Fields that can be used for predictive lead scoring computation"

    name = fields.Char(related="field_id.field_description")
    field_id = fields.Many2one(
        "ir.model.fields",
        domain=[("model_id.model", "=", "crm.lead")],
        required=True,
        ondelete="cascade",
    )
    color = fields.Integer("Color", default=lambda self: self._default_color())
