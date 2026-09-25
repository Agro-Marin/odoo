from odoo import fields, models
from odoo.tools import frozendict


class PurchaseReport(models.Model):
    _inherit = "purchase.report"
    _access_anchors = frozendict(
        {
            "team": models.Anchor("team_id", usage="purchase"),
        }
    )

    team_id = fields.Many2one(
        comodel_name="team.team",
        string="Purchase Team",
        readonly=True,
    )

    def _get_fields_select(self) -> dict:
        return super()._get_fields_select() | {"team_id": "o.team_id"}

    def _get_fields_group_by(self) -> list:
        return [*super()._get_fields_group_by(), "o.team_id"]
