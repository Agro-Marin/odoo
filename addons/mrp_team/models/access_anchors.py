from odoo import models
from odoo.tools import frozendict


class TeamMember(models.Model):
    _inherit = "team.member"

    _access_anchors = frozendict(
        {
            "owner": "team_id.user_id",
            "team": "team_id",
        }
    )
