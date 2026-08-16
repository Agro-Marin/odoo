import ast
import contextlib
import re
import typing
from collections import defaultdict
from email.message import EmailMessage
from typing import Literal, Self

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import is_html_empty, remove_accents

if typing.TYPE_CHECKING:
    from .mail_alias_domain import MailAliasDomain
    from odoo.addons.base.models.ir_model import IrModel

atext = r"[a-zA-Z0-9!#$%&'*+\-/=?^_`{|}~]"
dot_atom_text = re.compile(r"^%s+(\.%s+)*$" % (atext, atext))


class MailAlias(models.Model):
    _name = "mail.alias"
    _description = "Email Aliases"
    _order = "alias_model_id, alias_name"
    _rec_name = "alias_name"
    _rec_names_search = ["alias_name", "alias_domain"]

    alias_name = fields.Char(
        "Alias Name",
        copy=False,
        help="The name of the email alias, e.g. 'jobs' if you want to catch emails for <jobs@example.odoo.com>",
    )
    alias_full_name = fields.Char(
        "Alias Email",
        compute="_compute_alias_full_name",
        store=True,
        index="btree_not_null",
    )
    alias_domain_id: MailAliasDomain = fields.Many2one(
        "mail.alias.domain",
        string="Alias Domain",
        ondelete="restrict",
        default=lambda self: self.env.company.alias_domain_id,
    )
    alias_domain = fields.Char("Alias domain name", related="alias_domain_id.name")
    alias_model_id: IrModel = fields.Many2one(
        "ir.model",
        "Aliased Model",
        required=True,
        ondelete="cascade",
        help="The model (Odoo Document Kind) to which this alias "
        "corresponds. Any incoming email that does not reply to an "
        "existing record will cause the creation of a new record "
        "of this model (e.g. a Project Task)",
        domain="[('field_id.name', '=', 'message_ids'), ('abstract', '=', False), ('transient', '=', False)]",
    )
    alias_defaults = fields.Text(
        "Default Values",
        required=True,
        default="{}",
        help="A Python dictionary that will be evaluated to provide "
        "default values when creating new records for this alias.",
    )
    alias_force_thread_id = fields.Integer(
        "Record Thread ID",
        help="Optional ID of a thread (record) to which all incoming messages will be attached, even "
        "if they did not reply to it. If set, this will disable the creation of new records completely.",
    )
    alias_parent_model_id: IrModel = fields.Many2one(
        "ir.model",
        "Parent Model",
        help="Parent model holding the alias. The model holding the alias reference "
        "is not necessarily the model given by alias_model_id "
        "(example: project (parent_model) and task (model))",
    )
    alias_parent_thread_id = fields.Integer(
        "Parent Record Thread ID",
        help="ID of the parent record holding the alias (example: project holding the task creation alias)",
    )
    alias_contact = fields.Selection(
        [
            ("everyone", "Everyone"),
            ("partners", "Authenticated Partners"),
            ("followers", "Followers only"),
        ],
        default="everyone",
        string="Alias Contact Security",
        required=True,
        help="Policy to post a message on the document using the mailgateway.\n"
        "- everyone: everyone can post\n"
        "- partners: only authenticated partners\n"
        "- followers: only followers of the related document or members of following channels\n",
    )
    alias_incoming_local = fields.Boolean(
        "Local-part based incoming detection", default=False
    )
    alias_bounced_content = fields.Html(
        "Custom Bounced Message",
        translate=True,
        help="If set, this content will automatically be sent out to unauthorized users instead of the default message.",
    )
    alias_status = fields.Selection(
        [
            ("not_tested", "Not Tested"),
            ("valid", "Valid"),
            ("invalid", "Invalid"),
        ],
        compute="_compute_alias_status",
        store=True,
        help="Alias status assessed on the last message received.",
    )

    _name_domain_unique = models.UniqueIndex(
        "(alias_name, COALESCE(alias_domain_id, 0))"
    )

    @api.constrains(
        "alias_domain_id",
        "alias_force_thread_id",
        "alias_parent_model_id",
        "alias_parent_thread_id",
        "alias_model_id",
    )
    def _check_alias_domain_id_mc(self) -> None:
        tocheck = self.sudo().filtered(lambda alias: alias.alias_domain_id.company_ids)
        tocheck = tocheck.filtered(
            lambda alias: (
                (
                    not alias.alias_model_id.model
                    or alias.alias_model_id.model in self.env
                )
                and (
                    not alias.alias_parent_model_id.model
                    or alias.alias_parent_model_id.model in self.env
                )
            )
        )
        if not tocheck:
            return

        def _owner_model(alias: MailAlias) -> str:
            return alias.alias_parent_model_id.model

        def _owner_env(alias: MailAlias) -> models.Model:
            return self.env[_owner_model(alias)]

        def _target_model(alias: MailAlias) -> str:
            return alias.alias_model_id.model

        def _target_env(alias: MailAlias) -> models.Model:
            return self.env[_target_model(alias)]

        recs_by_model = defaultdict(list)
        for alias in tocheck:
            if alias.alias_parent_model_id and alias.alias_parent_thread_id:
                if _owner_env(alias)._mail_get_company_field():
                    recs_by_model[_owner_model(alias)].append(
                        alias.alias_parent_thread_id
                    )
            if alias.alias_model_id and alias.alias_force_thread_id:
                if _target_env(alias)._mail_get_company_field():
                    recs_by_model[_target_model(alias)].append(
                        alias.alias_force_thread_id
                    )

        def _fetch_owner(alias: MailAlias) -> models.Model | None:
            if (
                alias.alias_parent_thread_id
                in recs_by_model[alias.alias_parent_model_id.model]
            ):
                return (
                    _owner_env(alias)
                    .with_prefetch(recs_by_model[_owner_model(alias)])
                    .browse(alias.alias_parent_thread_id)
                )
            return None

        def _fetch_target(alias: MailAlias) -> models.Model | None:
            if alias.alias_force_thread_id in recs_by_model[alias.alias_model_id.model]:
                return (
                    _target_env(alias)
                    .with_prefetch(recs_by_model[_target_model(alias)])
                    .browse(alias.alias_force_thread_id)
                )
            return None

        for alias in tocheck:
            if owner := _fetch_owner(alias):
                company = owner[owner._mail_get_company_field()]
                if (
                    company
                    and company.alias_domain_id != alias.alias_domain_id
                    and alias.alias_domain_id.company_ids
                ):
                    raise ValidationError(
                        _(
                            "We could not create alias %(alias_name)s because domain "
                            "%(alias_domain_name)s belongs to company %(alias_company_names)s "
                            "while the owner document belongs to company %(company_name)s.",
                            alias_company_names=",".join(
                                alias.alias_domain_id.company_ids.mapped("name")
                            ),
                            alias_domain_name=alias.alias_domain_id.name,
                            alias_name=alias.display_name,
                            company_name=company.name,
                        )
                    )
            if target := _fetch_target(alias):
                company = target[target._mail_get_company_field()]
                if (
                    company
                    and company.alias_domain_id != alias.alias_domain_id
                    and alias.alias_domain_id.company_ids
                ):
                    raise ValidationError(
                        _(
                            "We could not create alias %(alias_name)s because domain "
                            "%(alias_domain_name)s belongs to company %(alias_company_names)s "
                            "while the target document belongs to company %(company_name)s.",
                            alias_company_names=",".join(
                                alias.alias_domain_id.company_ids.mapped("name")
                            ),
                            alias_domain_name=alias.alias_domain_id.name,
                            alias_name=alias.display_name,
                            company_name=company.name,
                        )
                    )

    @api.constrains("alias_name")
    def _check_alias_is_ascii(self) -> None:
        for alias in self.filtered("alias_name"):
            if not dot_atom_text.match(alias.alias_name):
                raise ValidationError(
                    _(
                        "You cannot use anything else than unaccented latin characters in the alias address %(alias_name)s.",
                        alias_name=alias.alias_name,
                    )
                )

    @api.constrains("alias_defaults")
    def _check_alias_defaults(self) -> None:
        for alias in self:
            try:
                dict(ast.literal_eval(alias.alias_defaults))
            except Exception as e:
                raise ValidationError(
                    _(
                        "Invalid expression, it must be a literal python dictionary definition e.g. \"{'field': 'value'}\""
                    )
                ) from e

    @api.constrains("alias_name", "alias_domain_id")
    def _check_alias_domain_clash(self) -> None:
        failing = self.filtered(
            lambda alias: (
                alias.alias_name
                and alias.alias_name
                in [
                    alias.alias_domain_id.bounce_alias,
                    alias.alias_domain_id.catchall_alias,
                ]
            )
        )
        if failing:
            raise ValidationError(
                _(
                    "Aliases %(alias_names)s is already used as bounce or catchall address. Please choose another alias.",
                    alias_names=", ".join(failing.mapped("display_name")),
                )
            )

    @api.depends("alias_domain_id.name", "alias_name")
    def _compute_alias_full_name(self) -> None:
        for record in self:
            if record.alias_domain_id and record.alias_name:
                record.alias_full_name = (
                    f"{record.alias_name}@{record.alias_domain_id.name}"
                )
            elif record.alias_name:
                record.alias_full_name = record.alias_name
            else:
                record.alias_full_name = False

    @api.depends("alias_domain", "alias_name")
    def _compute_display_name(self) -> None:
        for record in self:
            if record.alias_name and record.alias_domain:
                record.display_name = f"{record.alias_name}@{record.alias_domain}"
            elif record.alias_name:
                record.display_name = record.alias_name
            else:
                record.display_name = _("Inactive Alias")

    @api.depends("alias_contact", "alias_defaults", "alias_model_id")
    def _compute_alias_status(self) -> None:
        self.alias_status = "not_tested"

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        alias_names, alias_domains = [], []
        for vals in vals_list:
            vals["alias_name"] = self._sanitize_alias_name(vals.get("alias_name"))
            alias_names.append(vals["alias_name"])
            vals["alias_domain_id"] = vals.get(
                "alias_domain_id", self.env.company.alias_domain_id.id
            )
            alias_domains.append(
                self.env["mail.alias.domain"].browse(vals["alias_domain_id"])
            )

        self._check_unique(alias_names, alias_domains)
        return super().create(vals_list)

    def write(self, vals: ValuesType) -> Literal[True]:
        alias_names, alias_domains = [], []
        if "alias_name" in vals:
            vals["alias_name"] = self._sanitize_alias_name(vals["alias_name"])
        if vals.get("alias_name") and self.ids:
            alias_names = [vals["alias_name"]] * len(self)
        elif "alias_name" not in vals and "alias_domain_id" in vals:
            if [vals["alias_domain_id"]] != self.alias_domain_id.ids:
                alias_names = self.filtered("alias_name").mapped("alias_name")

        if alias_names:
            tocheck_records = (
                self if vals.get("alias_name") else self.filtered("alias_name")
            )
            if "alias_domain_id" in vals:
                alias_domains = [
                    self.env["mail.alias.domain"].browse(vals["alias_domain_id"])
                ] * len(tocheck_records)
            else:
                alias_domains = [record.alias_domain_id for record in tocheck_records]
            self._check_unique(alias_names, alias_domains)

        return super().write(vals)

    def _check_unique(
        self, alias_names: list[str], alias_domains: MailAliasDomain
    ) -> None:
        if len(alias_names) != len(alias_domains):
            names_repr = ", ".join(str(name) for name in alias_names)
            domains_repr = ", ".join(domain.display_name for domain in alias_domains)
            msg = (
                f"Invalid call to '_check_unique': names and domains should make coherent lists, "
                f"received {names_repr} and {domains_repr}"
            )
            raise ValueError(msg)

        domain_to_names = defaultdict(list)
        for alias_name, alias_domain in zip(alias_names, alias_domains, strict=False):
            if alias_name and alias_name in domain_to_names[alias_domain]:
                raise UserError(
                    _(
                        "Email aliases %(alias_name)s cannot be used on several records at the same time. Please update records one by one.",
                        alias_name=alias_name,
                    )
                )
            if alias_name:
                domain_to_names[alias_domain].append(alias_name)

        domain = Domain.OR(
            Domain("alias_name", "in", alias_names)
            & Domain("alias_domain_id", "=", alias_domain.id)
            for alias_domain, alias_names in domain_to_names.items()
        )
        if domain and self:
            domain &= Domain("id", "not in", self.ids)
        existing = self.search(domain, limit=1) if domain else self.env["mail.alias"]
        if not existing:
            return
        if existing.alias_parent_model_id and existing.alias_parent_thread_id:
            parent_name = (
                self.env[existing.alias_parent_model_id.model]
                .sudo()
                .browse(existing.alias_parent_thread_id)
                .display_name
            )
            msg_begin = _(
                "Alias %(matching_name)s (%(current_id)s) is already linked with %(alias_model_name)s (%(matching_id)s) and used by the %(parent_name)s %(parent_model_name)s.",
                alias_model_name=existing.alias_model_id.name,
                current_id=self.ids if self else _("your alias"),
                matching_id=existing.id,
                matching_name=existing.display_name,
                parent_name=parent_name,
                parent_model_name=existing.alias_parent_model_id.name,
            )
        else:
            msg_begin = _(
                "Alias %(matching_name)s (%(current_id)s) is already linked with %(alias_model_name)s (%(matching_id)s).",
                alias_model_name=existing.alias_model_id.name,
                current_id=self.ids if self else _("new"),
                matching_id=existing.id,
                matching_name=existing.display_name,
            )
        msg_end = _("Choose another value or change it on the other document.")
        raise UserError(f"{msg_begin} {msg_end}")  # pylint: disable=missing-gettext

    @api.model
    def _sanitize_allowed_domains(self, allowed_domains: str) -> str:
        value = [
            domain.strip().lower()
            for domain in allowed_domains.split(",")
            if domain.strip()
        ]
        if not value:
            raise ValidationError(
                _(
                    "Value %(allowed_domains)s for `mail.catchall.domain.allowed` cannot be validated.\n"
                    "It should be a comma separated list of domains e.g. example.com,example.org.",
                    allowed_domains=allowed_domains,
                )
            )
        return ",".join(value)

    @api.model
    def _sanitize_alias_name(
        self, name: str, is_email: bool = False
    ) -> str | Literal[False]:
        sanitized_name = name.strip() if name else ""
        if is_email:
            right_part = sanitized_name.lower().partition("@")[2]
        else:
            right_part = False
        if sanitized_name:
            sanitized_name = remove_accents(sanitized_name).lower().split("@")[0]
            sanitized_name = re.sub(r"^\.+|\.+$|\.+(?=\.)", "", sanitized_name)
            sanitized_name = re.sub(
                r"[^\w!#$%&\'*+\-/=?^_`{|}~.]+", "-", sanitized_name
            )
            sanitized_name = sanitized_name.encode("ascii", errors="ignore").decode()
        if not sanitized_name.strip():
            return False
        return (
            f"{sanitized_name}@{right_part}"
            if is_email and right_part
            else sanitized_name
        )

    @api.model
    def _is_encodable(self, alias_name: str, charset: str = "ascii") -> bool:
        try:
            remove_accents(alias_name).encode(charset)
        except UnicodeEncodeError:
            return False
        return True

    def open_document(self) -> dict | Literal[False]:
        if not self.alias_model_id or not self.alias_force_thread_id:
            return False
        return {
            "view_mode": "form",
            "res_model": self.alias_model_id.model,
            "res_id": self.alias_force_thread_id,
            "type": "ir.actions.act_window",
        }

    def open_parent_document(self) -> dict | Literal[False]:
        if not self.alias_parent_model_id or not self.alias_parent_thread_id:
            return False
        return {
            "view_mode": "form",
            "res_model": self.alias_parent_model_id.model,
            "res_id": self.alias_parent_thread_id,
            "type": "ir.actions.act_window",
        }

    def _get_alias_bounced_body(self, message_dict: dict) -> Markup:
        lang_author = False
        if message_dict.get("author_id"):
            with contextlib.suppress(Exception):
                lang_author = (
                    self.env["res.partner"].browse(message_dict["author_id"]).lang
                )

        if lang_author:
            self = self.with_context(lang=lang_author)

        if not is_html_empty(self.alias_bounced_content):
            body = self.alias_bounced_content
        else:
            body = self._get_alias_bounced_body_fallback(message_dict)
        return self.env["ir.qweb"]._render(
            "mail.mail_bounce_alias_security",
            {"body": body, "message": message_dict},
            minimal_qcontext=True,
        )

    def _get_alias_bounced_body_fallback(self, message_dict: dict) -> Markup:
        contact_description = self._get_alias_contact_description()
        default_email = (
            self.env.company.partner_id.email_formatted
            if self.env.company.partner_id.email
            else self.env.company.name
        )
        content = Markup(
            _("""The message below could not be accepted by the address %(alias_display_name)s.
                 Only %(contact_description)s are allowed to contact it.<br /><br />
                 Please make sure you are using the correct address or contact us at %(default_email)s instead.""")
        ) % {
            "alias_display_name": self.display_name,
            "contact_description": contact_description,
            "default_email": default_email,
        }
        return Markup(
            "<p>%(header)s,<br /><br />%(content)s<br /><br />%(regards)s</p>"
        ) % {
            "content": content,
            "header": _("Dear Sender"),
            "regards": _("Kind Regards"),
        }

    def _get_alias_contact_description(self) -> str:
        if self.alias_contact == "partners":
            return _("addresses linked to registered partners")
        return _("some specific addresses")

    def _get_alias_invalid_body(self, message_dict: dict) -> Markup:
        content = Markup(
            _("""The message below could not be accepted by the address %(alias_display_name)s.
Please try again later or contact %(company_name)s instead.""")
        ) % {
            "alias_display_name": self.display_name,
            "company_name": self.env.company.name,
        }
        return self.env["ir.qweb"]._render(
            "mail.mail_bounce_alias_security",
            {
                "body": Markup(
                    "<p>%(header)s,<br /><br />%(content)s<br /><br />%(regards)s</p>"
                )
                % {
                    "content": content,
                    "header": _("Dear Sender"),
                    "regards": _("Kind Regards"),
                },
                "message": message_dict,
            },
            minimal_qcontext=True,
        )

    def _alias_bounce_incoming_email(
        self, message: EmailMessage, message_dict: dict, set_invalid: bool = True
    ) -> None:
        self.ensure_one()
        if set_invalid:
            self.alias_status = "invalid"
            body = self._get_alias_invalid_body(message_dict)
        else:
            body = self._get_alias_bounced_body(message_dict)
        self.env["mail.thread"]._routing_create_bounce_email(
            message_dict["email_from"],
            body,
            message,
            references=self.env["mail.thread"]._routing_bounce_references(message_dict),
        )
