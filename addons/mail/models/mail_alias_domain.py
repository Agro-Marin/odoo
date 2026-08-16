import typing
from typing import Literal, Self

from odoo import _, api, exceptions, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError
from odoo.tools import ormcache

from odoo.addons.mail.models.mail_alias import dot_atom_text

if typing.TYPE_CHECKING:
    from odoo.addons.base.models.res_company import ResCompany


class MailAliasDomain(models.Model):
    _name = "mail.alias.domain"
    _description = "Email Domain"
    _order = "sequence ASC, id ASC"

    name = fields.Char(
        "Name",
        required=True,
        help="Email domain e.g. 'example.com' in 'odoo@example.com'",
    )
    company_ids: ResCompany = fields.One2many(
        "res.company",
        "alias_domain_id",
        string="Companies",
        help="Companies using this domain as default for sending mails",
    )
    sequence = fields.Integer(default=10)
    bounce_alias = fields.Char(
        "Bounce Alias",
        default="bounce",
        required=True,
        help="Local-part of email used for Return-Path used when emails bounce e.g. "
        "'bounce' in 'bounce@example.com'",
    )
    bounce_email = fields.Char("Bounce Email", compute="_compute_bounce_email")
    catchall_alias = fields.Char(
        "Catchall Alias",
        default="catchall",
        required=True,
        help="Local-part of email used for Reply-To to catch answers e.g. "
        "'catchall' in 'catchall@example.com'",
    )
    catchall_email = fields.Char("Catchall Email", compute="_compute_catchall_email")
    default_from = fields.Char(
        "Default From Alias",
        default="notifications",
        help="Default from when it does not match outgoing server filters. Can be either "
        "a local-part e.g. 'notifications' either a complete email address e.g. "
        "'notifications@example.com' to override all outgoing emails.",
    )
    default_from_email = fields.Char(
        "Default From", compute="_compute_default_from_email"
    )

    _bounce_email_uniques = models.Constraint(
        "UNIQUE(bounce_alias, name)",
        "Bounce emails should be unique",
    )
    _catchall_email_uniques = models.Constraint(
        "UNIQUE(catchall_alias, name)",
        "Catchall emails should be unique",
    )

    @api.depends("bounce_alias", "name")
    def _compute_bounce_email(self) -> None:
        self.bounce_email = ""
        for domain in self.filtered("bounce_alias"):
            domain.bounce_email = f"{domain.bounce_alias}@{domain.name}"

    @api.depends("catchall_alias", "name")
    def _compute_catchall_email(self) -> None:
        self.catchall_email = ""
        for domain in self.filtered("catchall_alias"):
            domain.catchall_email = f"{domain.catchall_alias}@{domain.name}"

    @api.depends("default_from", "name")
    def _compute_default_from_email(self) -> None:
        self.default_from_email = ""
        for domain in self.filtered("default_from"):
            if "@" in domain.default_from:
                domain.default_from_email = domain.default_from
            else:
                domain.default_from_email = f"{domain.default_from}@{domain.name}"

    @api.constrains("bounce_alias", "catchall_alias")
    def _check_bounce_catchall_uniqueness(self) -> None:
        names = self.filtered("bounce_alias").mapped("bounce_alias") + self.filtered(
            "catchall_alias"
        ).mapped("catchall_alias")
        if not names:
            return

        similar_domains = self.env["mail.alias.domain"].search(
            [("name", "in", self.mapped("name"))]
        )
        for tocheck in self:
            if any(
                similar.bounce_alias == tocheck.bounce_alias
                for similar in similar_domains
                if similar != tocheck and similar.name == tocheck.name
            ):
                raise exceptions.ValidationError(
                    _(
                        "Bounce alias %(bounce)s is already used for another domain with same name. "
                        "Use another bounce or simply use the other alias domain.",
                        bounce=tocheck.bounce_email,
                    )
                )
            if any(
                similar.catchall_alias == tocheck.catchall_alias
                for similar in similar_domains
                if similar != tocheck and similar.name == tocheck.name
            ):
                raise exceptions.ValidationError(
                    _(
                        "Catchall alias %(catchall)s is already used for another domain with same name. "
                        "Use another catchall or simply use the other alias domain.",
                        catchall=tocheck.catchall_email,
                    )
                )

        potential_aliases = self.env["mail.alias"].search(
            [("alias_name", "in", list(set(names))), ("alias_domain_id", "!=", False)]
        )
        existing = next(
            (
                alias
                for alias in potential_aliases
                if alias.display_name
                in (self.mapped("bounce_email") + self.mapped("catchall_email"))
            ),
            self.env["mail.alias"],
        )
        if existing:
            document_name = False
            if existing.alias_parent_model_id and existing.alias_parent_thread_id:
                document_name = (
                    self.env[existing.alias_parent_model_id.model]
                    .sudo()
                    .browse(existing.alias_parent_thread_id)
                    .display_name
                )
            elif existing.alias_model_id and existing.alias_force_thread_id:
                document_name = (
                    self.env[existing.alias_model_id.model]
                    .sudo()
                    .browse(existing.alias_force_thread_id)
                    .display_name
                )
            if document_name:
                raise exceptions.ValidationError(
                    _(
                        "Bounce/Catchall '%(matching_alias_name)s' is already used by %(document_name)s. Choose another alias or change it on the other document.",
                        matching_alias_name=existing.display_name,
                        document_name=document_name,
                    )
                )
            raise exceptions.ValidationError(
                _(
                    "Bounce/Catchall '%(matching_alias_name)s' is already used. Choose another alias or change it on the linked model.",
                    matching_alias_name=existing.display_name,
                )
            )

    @api.constrains("name")
    def _check_name(self) -> None:
        for domain in self:
            if not domain.name:
                raise exceptions.ValidationError(
                    _("You cannot assign an empty domain name.")
                )
            if not dot_atom_text.match(domain.name):
                raise exceptions.ValidationError(
                    _(
                        "You cannot use anything else than unaccented latin characters in the domain name %(domain_name)s.",
                        domain_name=domain.name,
                    )
                )

    @api.model
    @ormcache(cache="stable")
    def _get_config(self) -> tuple:
        domains = self.sudo().search([])
        return (
            tuple(domains.ids),
            tuple(filter(None, domains.mapped("name"))),
            tuple(filter(None, domains.mapped("bounce_email"))),
            tuple(filter(None, domains.mapped("catchall_email"))),
            tuple(filter(None, domains.mapped("default_from_email"))),
        )

    @api.model
    def _get_domain_names(self) -> tuple[str, ...]:
        return self._get_config()[1]

    @api.model
    def _get_bounce_emails(self) -> tuple[str, ...]:
        return self._get_config()[2]

    @api.model
    def _get_catchall_emails(self) -> tuple[str, ...]:
        return self._get_config()[3]

    @api.model
    def _get_default_from_emails(self) -> tuple[str, ...]:
        return self._get_config()[4]

    @api.model
    def _get_default_domain(self) -> Self:
        ids = self._get_config()[0]
        return self.browse(ids[:1])

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            self._sanitize_configuration(vals)

        alias_domains = super().create(vals_list)
        self.env.registry.clear_cache("stable")
        alias_domains._check_default_from_not_used_by_users()

        if alias_domains and self.search_count([]) == len(alias_domains):
            self.env["res.company"].with_context(active_test=False).search(
                [("alias_domain_id", "=", False)]
            ).alias_domain_id = alias_domains[0].id
            self.env["mail.alias"].sudo().search(
                [("alias_domain_id", "=", False)]
            ).alias_domain_id = alias_domains[0].id

        return alias_domains

    def write(self, vals: ValuesType) -> Literal[True]:
        self._sanitize_configuration(vals)
        ret = super().write(vals)
        self.env.registry.clear_cache("stable")
        self._check_default_from_not_used_by_users()
        return ret

    def unlink(self) -> Literal[True]:
        self.env.registry.clear_cache("stable")
        return super().unlink()

    def _check_default_from_not_used_by_users(self) -> None:
        match_from_filter = self.env["ir.mail_server"]._match_from_filter
        personal_mail_servers = (
            self.env["ir.mail_server"].sudo().search([("owner_user_id", "!=", False)])
        )
        if any(
            match_from_filter(e, server.from_filter)
            for e in self.mapped("default_from_email")
            for server in personal_mail_servers
        ):
            raise UserError(
                _("A personal mail server is using that address, you can not use it.")
            )

    @api.model
    def _sanitize_configuration(self, config_values: dict) -> dict:
        if config_values.get("bounce_alias"):
            config_values["bounce_alias"] = self.env["mail.alias"]._sanitize_alias_name(
                config_values["bounce_alias"]
            )
        if config_values.get("catchall_alias"):
            config_values["catchall_alias"] = self.env[
                "mail.alias"
            ]._sanitize_alias_name(config_values["catchall_alias"])
        if config_values.get("default_from"):
            config_values["default_from"] = self.env["mail.alias"]._sanitize_alias_name(
                config_values["default_from"], is_email=True
            )
        return config_values

    @api.model
    def _find_aliases(self, email_list: list[str]) -> list:
        filtered_emails = [e for e in email_list if e and "@" in e]
        if not filtered_emails:
            return filtered_emails
        _ids, _names, bounces, catchalls, default_froms = self._get_config()
        aliases = set(bounces + catchalls + default_froms)

        catchall_params = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.catchall.domain.allowed")
            or ""
        )
        catchall_domains_allowed = set(filter(None, catchall_params.split(",")))
        if catchall_domains_allowed:
            catchall_domains_allowed.update(_names)
            email_localparts_tocheck = [
                email.partition("@")[0]
                for email in filtered_emails
                if (email.partition("@")[2] in catchall_domains_allowed)
            ]
        else:
            email_localparts_tocheck = [
                email.partition("@")[0] for email in filtered_emails if email
            ]

        potential_aliases = self.env["mail.alias"].search(
            [
                "|",
                ("alias_full_name", "in", filtered_emails),
                "&",
                ("alias_name", "in", email_localparts_tocheck),
                ("alias_incoming_local", "=", True),
            ]
        )
        aliases.update(
            potential_aliases.filtered(lambda x: not x.alias_incoming_local).mapped(
                "alias_full_name"
            )
        )

        local_alias_names = set(
            potential_aliases.filtered(lambda x: x.alias_incoming_local).mapped(
                "alias_name"
            )
        )

        res = []
        for email in filtered_emails:
            if email in aliases:
                res.append(email)
                continue

            local_part, _sep, domain = email.partition("@")
            if local_part in local_alias_names and (
                not catchall_domains_allowed or domain in catchall_domains_allowed
            ):
                res.append(email)

        return res

    @api.model
    def _migrate_icp_to_domain(self) -> Self:
        Icp = self.env["ir.config_parameter"].sudo()
        alias_domain = Icp.get_param("mail.catchall.domain")
        if alias_domain:
            existing = self.search([("name", "=", alias_domain)])
            if existing:
                return existing
            bounce_alias = Icp.get_param("mail.bounce.alias")
            catchall_alias = Icp.get_param("mail.catchall.alias")
            default_from = Icp.get_param("mail.default.from")
            return self.create(
                {
                    "bounce_alias": bounce_alias or "bounce",
                    "catchall_alias": catchall_alias or "catchall",
                    "default_from": default_from or "notifications",
                    "name": alias_domain,
                }
            )
        return self.browse()
