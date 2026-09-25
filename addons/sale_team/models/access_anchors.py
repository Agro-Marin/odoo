from odoo import models
from odoo.tools import frozendict


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    _access_anchors = frozendict(
        {
            "sale_move_team": models.Anchor(
                "move_id.team_id", kind="team", usage="sale"
            ),
        }
    )


class AccountMoveSendBatchWizard(models.TransientModel):
    _inherit = "account.move.send.batch.wizard"

    _access_anchors = frozendict(
        {
            "team": models.Anchor("move_ids.team_id", usage="sale"),
        }
    )


class AccountMoveSendWizard(models.TransientModel):
    _inherit = "account.move.send.wizard"

    _access_anchors = frozendict(
        {
            "team": models.Anchor("move_id.team_id", usage="sale"),
        }
    )


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    _access_anchors = frozendict(
        {
            "team": models.Anchor("order_id.team_id", usage="sale"),
        }
    )


class TeamMember(models.Model):
    _inherit = "team.member"

    _access_anchors = frozendict(
        {
            "owner": "team_id.user_id",
            "team": "team_id",
        }
    )
