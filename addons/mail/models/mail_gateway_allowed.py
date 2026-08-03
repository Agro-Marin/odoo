from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError


class MailGatewayAllowed(models.Model):
    """Trusted senders exempted from the incoming mail gateway quota.

    Inbound emails are otherwise capped, per 'mail.gateway.loop.minutes'
    window, by 'mail.gateway.loop.threshold' records created or replies posted
    through an alias, which a legit automated source would exceed.
    """

    _name = "mail.gateway.allowed"
    _description = "Mail Gateway Allowed"

    email = fields.Char("Email Address", required=True)
    email_normalized = fields.Char(
        string="Normalized Email",
        compute="_compute_email_normalized",
        store=True,
        index=True,
    )

    @api.depends("email")
    def _compute_email_normalized(self):
        for record in self:
            record.email_normalized = tools.email_normalize(record.email)

    @api.constrains("email")
    def _check_email_normalizes(self):
        """Reject an entry whose address does not normalize."""
        # 'email' is only required, so a value like "Support Team" would store a
        # NULL 'email_normalized': a dead row loop detection can never match
        for record in self:
            if not tools.email_normalize(record.email):
                raise ValidationError(_("Invalid email address “%s”", record.email))

    @api.model
    def get_empty_list_help(self, help_message):
        icp = self.env["ir.config_parameter"]
        LOOP_MINUTES = icp._get_int_param("mail.gateway.loop.minutes", 120)
        LOOP_THRESHOLD = icp._get_int_param("mail.gateway.loop.threshold", 20)

        return Markup(
            _("""
            <p class="o_view_nocontent_smiling_face">
                Add addresses to the Allowed List
            </p><p>
                To protect you from spam and reply loops, Odoo automatically blocks emails
                coming to your gateway past a threshold of <b>%(threshold)i</b> emails every <b>%(minutes)i</b>
                minutes. If there are some addresses from which you need to receive very frequent
                updates, you can however add them below and Odoo will let them go through.
            </p>""")
        ) % {
            "threshold": LOOP_THRESHOLD,
            "minutes": LOOP_MINUTES,
        }
