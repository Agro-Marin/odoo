from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import email_normalize


class IrMail_Server(models.Model):
    _inherit = "ir.mail_server"
    _email_field = "smtp_user"

    mail_template_ids = fields.One2many(
        comodel_name="mail.template",
        inverse_name="mail_server_id",
        string="Mail template using this mail server",
        readonly=True,
    )

    owner_user_id = fields.Many2one("res.users", "Owner", copy=False)

    # throttle the personal mail servers: number of emails sent during the stored
    # minute, both reset at the next one (MailMail._split_by_delayed_batch)
    owner_limit_time = fields.Datetime("Owner Limit Time", copy=False)
    owner_limit_count = fields.Integer("Owner Limit Count", copy=False)

    _unique_owner_user_id = models.Constraint(
        "UNIQUE(owner_user_id)",
        "owner_user_id must be unique",
    )

    def _active_usages_compute(self):
        usages_super = super()._active_usages_compute()
        for record in self.filtered("mail_template_ids"):
            usages_super.setdefault(record.id, []).extend(
                self.env._("%s (Email Template)", t.display_name)
                for t in record.mail_template_ids
            )
        return usages_super

    @api.model
    def _get_default_bounce_address(self):
        """Compute the default bounce address. Try to use mail-defined config
        parameter bounce alias if set."""
        if self.env.company.bounce_email:
            return self.env.company.bounce_email
        return super()._get_default_bounce_address()

    @api.model
    def _get_default_from_address(self):
        """Default from: try to use default_from defined on company's alias
        domain."""
        if default_from := self.env.company.default_from_email:
            return default_from
        return super()._get_default_from_address()

    def _get_test_email_from(self):
        self.ensure_one()
        if mail_from := self._from_filter_sender():
            return mail_from
        if domain := self._from_filter_domain():
            # the mail server is configured for a domain that matches the default email address
            alias_domains = self.env["mail.alias.domain"].sudo().search([])
            matching = next(
                (
                    alias_domain
                    for alias_domain in alias_domains
                    if self._match_from_filter(
                        alias_domain.default_from_email, self.from_filter
                    )
                ),
                False,
            )
            if matching:
                return matching.default_from_email
            # fake default_from "odoo@domain"
            return f"odoo@{domain}"
        # no from_filter, or nothing usable in it -> fallback
        return super()._get_test_email_from()

    @api.model
    def _filter_mail_servers_fallback(self, servers):
        return servers.filtered(lambda s: not s.owner_user_id)

    def _find_mail_server_allowed_domain(self):
        """Restrict search to 'public' servers."""
        domain = super()._find_mail_server_allowed_domain()
        domain &= Domain("owner_user_id", "=", False)
        return domain

    def _check_forced_mail_server(self, mail_server, allow_archived, smtp_from):
        super()._check_forced_mail_server(mail_server, allow_archived, smtp_from)

        if mail_server.owner_user_id:
            # Both sides normalized: from_filter is a plain editable Char, so a
            # stored "Owner@Example.com" or a stray space used to fail this exact
            # match and lock the owner out of their own server. Deliberately not
            # _match_from_filter -- that also accepts a whole domain, which would
            # let a personal server send as anyone in it.
            if email_normalize(smtp_from) != email_normalize(mail_server.from_filter):
                raise UserError(
                    _(
                        'The server "%s" cannot be forced as it belongs to a user.',
                        mail_server.display_name,
                    )
                )
            if not mail_server.active:
                raise UserError(
                    _(
                        'The server "%s" cannot be forced as it belongs to a user and is archived.',
                        mail_server.display_name,
                    )
                )
            if mail_server.owner_user_id.outgoing_mail_server_id != mail_server:
                raise UserError(
                    _(
                        'The server "%s" cannot be forced as the owner does not use it anymore.',
                        mail_server.display_name,
                    )
                )

    def _get_personal_mail_servers_limit(self):
        """Return the number of email we can send in 1 minutes for this outgoing server.

        0 fallbacks to 30 to avoid blocking servers.
        """
        return (
            self.env["ir.config_parameter"]._get_int_param(
                "mail.server.personal.limit.minutes", 30
            )
            or 30
        )
