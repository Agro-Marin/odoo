from odoo import _, exceptions, fields, models


class GamificationBadgeUserWizard(models.TransientModel):
    """Wizard for granting a badge to a user."""

    _name = "gamification.badge.user.wizard"
    _description = "Gamification User Badge Wizard"

    user_id = fields.Many2one("res.users", string="User", required=True)
    badge_id = fields.Many2one("gamification.badge", string="Badge", required=True)
    comment = fields.Text("Comment")

    def action_grant_badge(self) -> bool:
        """Grant a badge to the selected user and send a notification."""
        BadgeUser = self.env["gamification.badge.user"]
        uid = self.env.uid
        for wiz in self:
            if uid == wiz.user_id.id:
                raise exceptions.UserError(_("You can not grant a badge to yourself."))
            BadgeUser.create(
                {
                    "user_id": wiz.user_id.id,
                    "sender_id": uid,
                    "badge_id": wiz.badge_id.id,
                    "comment": wiz.comment,
                }
            )._send_badge()
        return True
