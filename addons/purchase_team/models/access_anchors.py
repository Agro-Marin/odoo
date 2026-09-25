from odoo import models
from odoo.tools import frozendict


class AccountMove(models.Model):
    _inherit = "account.move"

    _access_anchors = frozendict(
        {
            "team": models.Anchor(
                "invoice_user_id.purchase_team_ids", usage="purchase"
            ),
        }
    )


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    _access_anchors = frozendict(
        {
            "team": models.Anchor(
                "move_id.invoice_user_id.purchase_team_ids", usage="purchase"
            ),
        }
    )


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    _access_anchors = frozendict(
        {
            "team": models.Anchor("order_id.team_id", usage="purchase"),
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
