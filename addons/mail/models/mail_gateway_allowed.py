from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError


class MailGatewayAllowed(models.Model):
    """List of trusted email address which won't have the quota restriction.

    The incoming emails have a restriction of the number of records they can
    create with alias, defined by the 2 systems parameters;
    - mail.gateway.loop.minutes
    - mail.gateway.loop.threshold

    But we might have some legit use cases for which we want to receive a ton of emails
    from an automated-source. This model stores those trusted source and this restriction
    won't apply to them.
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
        """Reject an entry whose address does not normalize.

        ``email`` is only ``required``; a value like "Support Team" stored a
        NULL ``email_normalized`` (indexed, searched with ``=``). Such a row is
        a meaningless no-op -- it can never match a real normalized ``From``,
        and matching an unparseable ``From`` (also NULL) has no effect either,
        since loop detection already treats a null sender as a no-op. Refuse the
        bad value at the source anyway, the way ``mail.blacklist`` does, so the
        allow list cannot accumulate confusing dead rows.
        """
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
