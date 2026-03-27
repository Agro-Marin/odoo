from typing import Any, Self

from odoo import _, api, fields, models
from odoo.orm.primitives import ValuesType


class GamificationBadgeUser(models.Model):
    """User having received a badge"""

    _name = "gamification.badge.user"
    _description = "Gamification User Badge"
    _inherit = ["mail.thread"]
    _order = "create_date desc"
    _rec_name = "badge_name"

    user_id = fields.Many2one(
        "res.users", string="User", required=True, ondelete="cascade", index=True
    )
    user_partner_id = fields.Many2one("res.partner", related="user_id.partner_id")
    sender_id = fields.Many2one("res.users", string="Sender")
    badge_id = fields.Many2one(
        "gamification.badge",
        string="Badge",
        required=True,
        ondelete="cascade",
        index=True,
    )
    challenge_id = fields.Many2one("gamification.challenge", string="Challenge")
    comment = fields.Text("Comment")
    badge_name = fields.Char(related="badge_id.name", string="Badge Name")
    level = fields.Selection(
        string="Badge Level", related="badge_id.level", store=True, readonly=True
    )

    def _send_badge(self) -> bool:
        """Send a notification to each user for receiving a badge.

        Does not verify constraints on badge granting — the caller
        (typically ``create``) is responsible for that.
        """
        template = self.env.ref("gamification.email_template_badge_received")
        rendered = template._render_field("body_html", self.ids)
        for badge_user in self:
            badge_user.message_notify(
                model=badge_user._name,
                res_id=badge_user.id,
                body=rendered[badge_user.id],
                partner_ids=[badge_user.user_partner_id.id],
                subject=_(
                    "You've earned the %(badge)s badge!", badge=badge_user.badge_name
                ),
                subtype_xmlid="mail.mt_comment",
                email_layout_xmlid="mail.mail_notification_layout",
            )
            # Real-time bus notification
            badge_user.user_id._send_gamification_notification(
                "badge",
                {
                    "title": _("Badge Earned!"),
                    "message": badge_user.badge_name,
                },
            )
            # Log to unified activity feed
            self.env["gamification.activity"]._log_badge(
                badge_user.user_id,
                badge_user.badge_id,
                badge_user.sender_id,
            )

        return True

    def _notify_get_recipients_groups(
        self, message, model_description, msg_vals=False
    ) -> list[list[Any]]:
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals
        )
        self.ensure_one()
        for group in groups:
            if group[0] == "user":
                group[2]["has_button_access"] = False
        return groups

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            self.env["gamification.badge"].browse(vals["badge_id"]).check_granting()
        return super().create(vals_list)

    def _mail_get_partner_fields(self, introspect_fields: bool = False) -> list[str]:
        return ["user_partner_id"]
