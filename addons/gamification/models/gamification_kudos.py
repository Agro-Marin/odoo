from typing import Self

from markupsafe import Markup, escape

from odoo import _, api, exceptions, fields, models
from odoo.models import ValuesType


class GamificationKudosCategory(models.Model):
    """Category for peer recognition kudos (e.g. Teamwork, Innovation, Quality)."""

    _name = "gamification.kudos.category"
    _description = "Kudos Category"
    _order = "sequence, name"

    name = fields.Char("Category", required=True, translate=True)
    description = fields.Text("Description", translate=True)
    sequence = fields.Integer(default=10)
    icon = fields.Char(
        "Icon CSS Class",
        default="fa fa-thumbs-up",
        help="Font Awesome icon class, e.g. 'fa fa-star', 'fa fa-heart'.",
    )
    color = fields.Integer("Color Index", default=0)
    karma_granted = fields.Integer(
        "Karma Bonus",
        default=5,
        help="Karma automatically granted to the recipient when kudos is sent.",
    )
    active = fields.Boolean(default=True)
    kudos_count = fields.Integer("# Kudos", compute="_compute_kudos_count")

    def _compute_kudos_count(self) -> None:
        """Count kudos per category."""
        if not self.ids:
            for rec in self:
                rec.kudos_count = 0
            return
        data = self.env["gamification.kudos"]._read_group(
            [("category_id", "in", self.ids)],
            groupby=["category_id"],
            aggregates=["__count"],
        )
        count_map = {cat.id: count for cat, count in data}
        for rec in self:
            rec.kudos_count = count_map.get(rec.id, 0)


class GamificationKudos(models.Model):
    """Peer-to-peer recognition message.

    Kudos are lightweight, informal recognition acts. Unlike badges (which
    have granting rules and scarcity), any employee can send kudos to any
    other employee at any time. Kudos integrate with mail.thread so they
    appear in the Discuss social feed.
    """

    _name = "gamification.kudos"
    _description = "Peer Recognition"
    _inherit = ["mail.thread"]
    _order = "create_date desc"
    _rec_name = "summary"

    sender_id = fields.Many2one(
        "res.users",
        string="From",
        required=True,
        readonly=True,
        default=lambda self: self.env.uid,
        index=True,
        ondelete="cascade",
    )
    sender_partner_id = fields.Many2one(
        "res.partner",
        string="Sender Partner",
        related="sender_id.partner_id",
        store=True,
    )
    recipient_id = fields.Many2one(
        "res.users",
        string="To",
        required=True,
        index=True,
        ondelete="cascade",
    )
    recipient_partner_id = fields.Many2one(
        "res.partner",
        string="Recipient Partner",
        related="recipient_id.partner_id",
        store=True,
    )
    category_id = fields.Many2one(
        "gamification.kudos.category",
        string="Category",
        required=True,
        ondelete="restrict",
    )
    message = fields.Text("Message", required=True)
    summary = fields.Char("Summary", compute="_compute_summary", store=True)
    karma_granted = fields.Integer(
        "Karma Granted",
        readonly=True,
        help="Karma points granted to the recipient.",
    )

    @api.depends("sender_id", "recipient_id", "category_id")
    def _compute_summary(self) -> None:
        """Generate a one-line summary for display."""
        for kudos in self:
            kudos.summary = _(
                "%(sender)s recognized %(recipient)s for %(category)s",
                sender=kudos.sender_id.name or "",
                recipient=kudos.recipient_id.name or "",
                category=kudos.category_id.name or "",
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Validate and create kudos, granting karma and posting notifications."""
        for vals in vals_list:
            # A non-system caller can only send kudos *as themselves*: force the
            # sender to the current user so a spoofed ``sender_id`` cannot be used
            # to impersonate a colleague or farm karma onto oneself.
            if not self.env.su:
                vals["sender_id"] = self.env.uid
            if vals.get("sender_id", self.env.uid) == vals.get("recipient_id"):
                raise exceptions.UserError(_("You cannot send kudos to yourself."))

        records = super().create(vals_list)

        for kudos in records:
            # Grant karma to recipient
            karma = kudos.category_id.karma_granted
            if karma:
                kudos.recipient_id.sudo()._add_karma(
                    karma,
                    source=kudos.sender_id,
                    reason=_("Kudos: %s", kudos.category_id.name),
                )
                kudos.karma_granted = karma

            # Post to mail thread for social visibility
            # Use Markup so HTML tags render; %-formatting auto-escapes str values
            body = Markup(
                '<i class="%s"/> <b>%s</b> recognized <b>%s</b> for <em>%s</em>: %s'
            ) % (
                escape(kudos.category_id.icon or ""),
                kudos.sender_id.name,
                kudos.recipient_id.name,
                kudos.category_id.name,
                kudos.message,
            )
            kudos.message_post(
                body=body,
                partner_ids=[kudos.recipient_partner_id.id],
                subtype_xmlid="mail.mt_comment",
                email_layout_xmlid="mail.mail_notification_light",
            )

            # Log to unified activity feed
            self.env["gamification.activity"]._log_kudos(
                kudos.sender_id,
                kudos.recipient_id,
                kudos.category_id,
                karma,
            )

        return records

    def _mail_get_partner_fields(self, introspect_fields: bool = False) -> list[str]:
        return ["recipient_partner_id"]
