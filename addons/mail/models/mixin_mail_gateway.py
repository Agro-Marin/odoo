import datetime
import email
import email.policy
import enum
import logging
import time
import typing
from collections.abc import Iterable
from datetime import UTC
from email import message_from_string
from email.message import EmailMessage
from typing import Literal, NamedTuple
from xmlrpc import client as xmlrpclib

import dateutil
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.tools import SQL, html2plaintext, ormcache
from odoo.tools.mail import (
    decode_message_header,
    email_normalize,
    email_normalize_all,
    email_split,
    email_split_and_format,
    formataddr,
    generate_tracking_message_id,
    unfold_references,
)

from odoo.addons.mail.tools import mime
from odoo.addons.mail.tools.mime import Attachment

if typing.TYPE_CHECKING:
    from .mail_alias import MailAlias
    from .mail_message import MailMessage
    from .res_partner import ResPartner
    from odoo.addons.bus.models.res_users import ResUsers


class RouteVerdict(enum.Enum):
    UNUSABLE = "unusable"
    REFUSED = "refused"


class Route(NamedTuple):
    model: str
    thread_id: int | Literal[False] | None
    custom_values: dict | Literal[False] | None
    uid: int
    alias: MailAlias | None


class RoutingRecipients(NamedTuple):
    email_to: list[str]
    email_to_localparts: list[str]
    rcpt_tos: list[str]
    rcpt_tos_localparts: list[str]
    rcpt_tos_valid: list[str]
    rcpt_tos_valid_localparts: list[str]


_logger = logging.getLogger(__name__)


def _dedup_ordered(emails: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(emails))


def _headers_to_emails(message: EmailMessage, headers: Iterable[str]) -> list[str]:
    return [
        formatted_email
        for header in headers
        if (address := decode_message_header(message, header, separator=","))
        for formatted_email in email_split_and_format(address)
    ]


class MixinMailGateway(models.AbstractModel):
    _name = "mixin.mail.gateway"
    _description = "Mail Gateway"

    _Attachment = Attachment

    def _mail_is_thread(self, record_or_model: models.BaseModel) -> bool:
        return isinstance(record_or_model, self.pool["mixin.mail.thread"])

    def _routing_warn(
        self,
        error_message: str,
        message_id: str,
        route: Route,
        raise_exception: bool = True,
    ) -> None:
        short_message = _("Mailbox unavailable - %s", error_message)
        full_message = "Routing mail with Message-Id %s: route %s: %s" % (
            message_id,
            route,
            error_message,
        )
        _logger.info(full_message)
        if raise_exception:
            raise ValueError(short_message)

    def _routing_create_bounce_email(
        self, email_from: str, body_html: Markup, message: EmailMessage, **mail_values
    ) -> None:
        bounce_to = decode_message_header(message, "Return-Path") or email_from
        bounced_subject = decode_message_header(message, "Subject")
        bounce_mail_values = {
            "author_id": False,
            "body_html": body_html,
            "subject": f"Re: {bounced_subject}" if bounced_subject else "Re:",
            "email_to": bounce_to,
            "auto_delete": True,
        }

        bounce_mail_values["email_from"] = self._routing_get_bounce_from(message)
        bounce_mail_values.update(mail_values)
        self.env["mail.mail"].sudo().create(bounce_mail_values).send()

    def _routing_get_bounce_from(self, message: EmailMessage) -> str:
        if bounce_from := self.env.company.bounce_email:
            return formataddr(("MAILER-DAEMON", bounce_from))

        alias_domain_names = self.env["mail.alias.domain"]._get_domain_names()
        catchall_aliases = self.env["mail.alias.domain"]._get_catchall_emails()
        recipients = [
            email_normalize(recipient) or recipient
            for recipient in email_split(
                decode_message_header(message, "To", separator=",")
            )
        ]
        for recipient in recipients:
            if recipient in catchall_aliases:
                continue
            if recipient.rsplit("@", 1)[-1] in alias_domain_names:
                return recipient

        noreply = (
            self.env.company.default_from_email
            or self.env.company.catchall_email
            or self.env["mail.alias.domain"]._get_default_domain().default_from_email
        )
        return formataddr(("MAILER-DAEMON", noreply or self.env.user.email_normalized))

    @api.model
    @ormcache()
    def _mail_get_blacklist_models(self) -> tuple[str, ...]:
        bl_models = (
            self.env["ir.model"]
            .sudo()
            .search(
                [
                    ("is_mail_blacklist", "=", True),
                    ("model", "!=", "mixin.mail.thread.blacklist"),
                ]
            )
        )
        return tuple(model.model for model in bl_models if model.model in self.env)

    @api.model
    def _routing_bounce_increment(
        self,
        bounced_record: models.BaseModel | Literal[False],
        bounced_model: str | Literal[False],
        bounced_email: str,
        bounced_partner: ResPartner,
    ) -> None:
        counted_bounced_record = False
        for model_name in self._mail_get_blacklist_models():
            holders = (
                self.env[model_name]
                .sudo()
                .search([("email_normalized", "=", bounced_email)])
            )
            holders._message_receive_bounce(bounced_email, bounced_partner)
            counted_bounced_record = counted_bounced_record or (
                bounced_record
                and model_name == bounced_model
                and bounced_record in holders
            )
        if (
            bounced_record
            and not counted_bounced_record
            and isinstance(bounced_record, self.pool["mixin.mail.thread"])
        ):
            bounced_record._message_receive_bounce(bounced_email, bounced_partner)

    @api.model
    def _routing_bounce_mark_notifications(
        self,
        bounced_message: MailMessage,
        bounced_email: str,
        bounced_partner: ResPartner,
        message_dict: dict,
    ) -> None:
        sub_domains = []
        if bounced_partner:
            sub_domains.append(Domain("res_partner_id", "in", bounced_partner.ids))
        if bounced_email:
            sub_domains.append(Domain("mail_email_address", "=", bounced_email))
        self.env["mail.notification"].sudo().search(
            Domain("mail_message_id", "=", bounced_message.id) & Domain.OR(sub_domains)
        ).write(
            {
                "failure_reason": html2plaintext(message_dict.get("body") or ""),
                "failure_type": "mail_bounce",
                "notification_status": "bounce",
            }
        )

    @api.model
    def _routing_handle_bounce(
        self, email_message: EmailMessage, message_dict: dict
    ) -> None:
        bounced_record = False
        bounced_email, bounced_partner = (
            message_dict["bounced_email"],
            message_dict["bounced_partner"],
        )
        bounced_msg_ids, bounced_message = (
            message_dict["bounced_msg_ids"],
            message_dict["bounced_message"],
        )

        if bounced_email:
            bounced_model, bounced_res_id = (
                bounced_message.model,
                bounced_message.res_id,
            )

            if bounced_model and bounced_model in self.env and bounced_res_id:
                bounced_record = (
                    self.env[bounced_model].sudo().browse(bounced_res_id).exists()
                )

            self._routing_bounce_increment(
                bounced_record, bounced_model, bounced_email, bounced_partner
            )
            if bounced_message and (bounced_email or bounced_partner):
                self._routing_bounce_mark_notifications(
                    bounced_message, bounced_email, bounced_partner, message_dict
                )

        if bounced_record:
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: not routing bounce email from %s replying to %s (model %s ID %s)",
                message_dict["email_from"],
                message_dict["to"],
                message_dict["message_id"],
                bounced_email,
                bounced_msg_ids,
                bounced_model,
                bounced_res_id,
            )
        elif bounced_email:
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: not routing bounce email from %s replying to %s (no document found)",
                message_dict["email_from"],
                message_dict["to"],
                message_dict["message_id"],
                bounced_email,
                bounced_msg_ids,
            )
        else:
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: not routing bounce email.",
                message_dict["email_from"],
                message_dict["to"],
                message_dict["message_id"],
            )

    @api.model
    def _routing_check_route(
        self,
        message: EmailMessage,
        message_dict: dict,
        route: Route,
        raise_exception: bool = True,
    ) -> Route | RouteVerdict:
        target = self._routing_check_target(message_dict, route, raise_exception)
        if target is None:
            return RouteVerdict.UNUSABLE
        record_set, thread_id = target
        if route.alias and not self._routing_check_alias_accepts(
            message, message_dict, route, record_set, thread_id
        ):
            return RouteVerdict.REFUSED
        return route._replace(thread_id=thread_id)

    @api.model
    def _routing_check_target(
        self, message_dict: dict, route: Route, raise_exception: bool
    ) -> tuple[models.BaseModel, int | Literal[False] | None] | None:
        message_id = message_dict["message_id"]
        model, thread_id = route.model, route.thread_id

        if not model:
            self._routing_warn(
                _("target model unspecified"), message_id, route, raise_exception
            )
            return None
        if model not in self.env:
            self._routing_warn(
                _("unknown target model %s", model), message_id, route, raise_exception
            )
            return None
        record_set = self.env[model].browse(thread_id) if thread_id else self.env[model]
        if record_set._abstract or record_set._transient:
            self._routing_warn(
                _("target model %s stores no document", model),
                message_id,
                route,
                raise_exception,
            )
            return None

        if thread_id:
            if not record_set.exists():
                self._routing_warn(
                    _(
                        "reply to missing document (%(model)s,%(thread)s), fall back on document creation",
                        model=model,
                        thread=thread_id,
                    ),
                    message_id,
                    route,
                    False,
                )
                thread_id = None
            elif not self._mail_is_thread(record_set):
                self._routing_warn(
                    _(
                        "reply to model %s that does not accept document update, fall back on document creation",
                        model,
                    ),
                    message_id,
                    route,
                    False,
                )
                thread_id = None

        if not thread_id and model and not self._mail_is_thread(record_set):
            self._routing_warn(
                _("model %s does not accept document creation", model),
                message_id,
                route,
                raise_exception,
            )
            return None

        return record_set, thread_id

    @api.model
    def _routing_check_alias_accepts(
        self,
        message: EmailMessage,
        message_dict: dict,
        route: Route,
        record_set: models.BaseModel,
        thread_id: int | Literal[False] | None,
    ) -> bool:
        alias, model = route.alias, route.model
        message_id = message_dict["message_id"]
        if not message_dict.get("author_id"):
            self._routing_find_author(
                message_dict, self._routing_link_document(record_set, alias)
            )

        if thread_id:
            obj = record_set[0]
        else:
            obj = alias._alias_get_document("owner") or self.env[model]
        error = obj._alias_get_error(message, message_dict, alias)
        if error:
            self._routing_warn(
                _(
                    "alias %(name)s: %(error)s",
                    name=alias.alias_name,
                    error=error.message or _("unknown error"),
                ),
                message_id,
                route,
                False,
            )
            self._routing_bounce_alias(
                alias, message, message_dict, is_config_error=error.is_config_error
            )
            return False
        return True

    @api.model
    def _routing_link_document(
        self, record_set: models.BaseModel, alias: MailAlias | None
    ) -> models.BaseModel:
        link_doc = record_set
        if not link_doc and alias:
            link_doc = alias._alias_get_document("owner")
        if link_doc and self._mail_is_thread(link_doc):
            return link_doc
        return self.env["mixin.mail.thread"]

    @api.model
    def _routing_find_author(
        self, message_dict: dict, link_doc: models.BaseModel
    ) -> ResPartner:
        email_from = message_dict.get("email_from")
        if not email_from:
            return self.env["res.partner"]
        cache = message_dict.setdefault("author_lookups", {})
        key = (link_doc._name, link_doc.id)
        if key not in cache:
            found = link_doc._partner_find_from_emails_single(
                [email_from], no_create=True
            )
            cache[key] = found.id if found else False
            if found and not message_dict.get("author_id"):
                message_dict["author_id"] = found.id
        return self.env["res.partner"].browse(cache[key] or ())

    @api.model
    def _routing_reset_bounce(
        self, email_message: EmailMessage, message_dict: dict
    ) -> None:
        normalized_from = email_normalize(message_dict["email_from"])
        if normalized_from:
            for model_name in self._mail_get_blacklist_models():
                self.env[model_name].sudo().search(
                    [
                        ("message_bounce", ">", 0),
                        ("email_normalized", "=", normalized_from),
                    ]
                )._message_reset_bounce(normalized_from)

    @api.model
    def _detect_is_bounce(self, message: EmailMessage, message_dict: dict) -> bool:
        bounce_aliases = self.env["mail.alias.domain"]._get_bounce_emails()
        email_to_list = [
            email_normalize(e) or e for e in email_split(message_dict["to"])
        ]
        if bounce_aliases and any(email in bounce_aliases for email in email_to_list):
            return True

        email_from = message_dict["email_from"]
        email_from_localpart = (
            (email_split(email_from) or [""])[0].split("@", 1)[0].lower()
        )

        if email_from_localpart == "mailer-daemon":
            return True

        content_type = message.get_content_type()
        raw_content_type = (
            (message.get("Content-Type") or "")
            .lower()
            .replace(" ", "")
            .replace('"', "")
        )
        return content_type == "multipart/report" or raw_content_type.startswith(
            "multipart/report"
        )

    @api.model
    def _detect_loop_sender_domain(
        self, email_from_normalized: str | Literal[False]
    ) -> list[str | tuple] | None:
        if not email_from_normalized:
            return None

        primary_email = self._mail_get_primary_email_field()
        if primary_email:
            escaped = (
                email_from_normalized.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            return [
                "|",
                (primary_email, "=ilike", escaped),
                (primary_email, "=ilike", f"%<{escaped}>"),
            ]

        _logger.info("Primary email missing on %s", self._name)
        return None

    @api.model
    def _detect_loop_sender_created_too_many(
        self,
        thread_ids: list,
        email_from_normalized: str | Literal[False],
        create_date_limit: datetime.datetime,
        threshold: int,
    ) -> bool:
        if not any(not thread_id for thread_id in thread_ids):
            return False
        base_domain = self._detect_loop_sender_domain(email_from_normalized)
        if not base_domain:
            return False
        return (
            self.sudo().search_count(
                Domain.AND([[("create_date", ">=", create_date_limit)], base_domain])
            )
            >= threshold
        )

    @api.model
    def _detect_loop_sender_replied_too_often(
        self,
        thread_ids: list,
        email_from: str,
        email_from_normalized: str | Literal[False],
        author_id: int | Literal[False],
        create_date_limit: datetime.datetime,
        threshold: int,
    ) -> bool:
        doc_ids = list(filter(None, thread_ids))
        if not doc_ids:
            return False
        domain = Domain(
            [
                ("model", "=", self._name),
                ("res_id", "in", doc_ids),
                ("create_date", ">=", create_date_limit),
                ("message_type", "=", "email"),
            ]
        )
        domain &= (
            Domain("author_id", "=", author_id)
            if author_id
            else Domain("email_from", "in", [email_from, email_from_normalized])
        )
        return any(
            count >= threshold
            for __, count in self.env["mail.message"]
            .sudo()
            ._read_group(domain, ["res_id"], ["__count"])
        )

    @api.model
    def _detect_loop_sender(
        self, message: EmailMessage, message_dict: dict, routes: list[Route]
    ) -> bool:
        email_from = message_dict.get("email_from")
        if not email_from:
            return False

        email_from_normalized = email_normalize(email_from)

        if email_from_normalized and self.env[
            "mail.gateway.allowed"
        ].sudo().search_count(
            [("email_normalized", "=", email_from_normalized)], limit=1
        ):
            return False

        icp = self.env["ir.config_parameter"]
        LOOP_MINUTES = icp._get_int_param("mail.gateway.loop.minutes", 120)
        LOOP_THRESHOLD = icp._get_int_param("mail.gateway.loop.threshold", 20)

        create_date_limit = self.env.cr.now() - datetime.timedelta(minutes=LOOP_MINUTES)
        author_id = message_dict.get("author_id")

        model_res_ids = {}
        for model, thread_id, *__ in routes or []:
            model_res_ids.setdefault(model, []).append(thread_id)

        for model_name, thread_ids in model_res_ids.items():
            model = self.env[model_name]
            if not self._mail_is_thread(model):
                continue

            loop_new = model._detect_loop_sender_created_too_many(
                thread_ids, email_from_normalized, create_date_limit, LOOP_THRESHOLD
            )
            loop_update = not loop_new and model._detect_loop_sender_replied_too_often(
                thread_ids,
                email_from,
                email_from_normalized,
                author_id,
                create_date_limit,
                LOOP_THRESHOLD,
            )

            if loop_new or loop_update:
                if loop_new:
                    _logger.info(
                        "--> ignored mail from %s to %s with Message-Id %s: created too many <%s>",
                        message_dict.get("email_from"),
                        message_dict.get("to"),
                        message_dict.get("message_id"),
                        model,
                    )
                if loop_update:
                    _logger.info(
                        "--> ignored mail from %s to %s with Message-Id %s: too much replies on same <%s>",
                        message_dict.get("email_from"),
                        message_dict.get("to"),
                        message_dict.get("message_id"),
                        model,
                    )
                body = self.env["ir.qweb"]._render(
                    "mail.message_notification_limit_email",
                    {"email": message_dict.get("to")},
                    minimal_qcontext=True,
                    raise_if_not_found=False,
                )
                self._routing_create_bounce_email(
                    email_from,
                    body,
                    message,
                    references=self._routing_bounce_references(message_dict),
                )
                return True

        return False

    @api.model
    def _routing_filter_local_aliases(
        self, aliases: MailAlias, rcpt_tos_valid_list: list[str]
    ) -> MailAlias:
        addressed = frozenset(rcpt_tos_valid_list)
        claimed_localparts = {
            alias.alias_full_name.split("@", 1)[0]
            for alias in aliases
            if alias.alias_full_name in addressed
        }
        return aliases.filtered(
            lambda alias: (
                alias.alias_full_name in addressed
                or alias.alias_name not in claimed_localparts
            )
        )

    @api.model
    def _routing_bounce_alias(
        self,
        alias: MailAlias,
        message: EmailMessage,
        message_dict: dict,
        is_config_error: bool = True,
    ) -> None:
        if is_config_error:
            alias._alias_mark_invalid()
        self._routing_create_bounce_email(
            message_dict["email_from"],
            alias._alias_get_bounce_body(message_dict, is_config_error=is_config_error),
            message,
            references=self._routing_bounce_references(message_dict),
        )

    @api.model
    def _routing_bounce_references(self, message_dict: dict) -> str:
        return (
            f"{message_dict['message_id']} "
            f"{generate_tracking_message_id('loop-detection-bounce-email')}"
        )

    @api.model
    def _detect_loop_headers(self, msg_dict: dict) -> bool:
        references = unfold_references(msg_dict["references"]) + [
            msg_dict["in_reply_to"]
        ]
        if references and any(
            "-loop-detection-bounce-email@" in ref for ref in references
        ):
            _logger.info("Email is a reply to the bounce notification, ignoring it.")
            return True

        return False

    @api.model
    def _detect_write_to_catchall(
        self,
        msg_dict: dict,
        catchall_aliases: list[str] | None = None,
        match_any: bool = False,
    ) -> bool:
        if catchall_aliases is None:
            catchall_aliases = self.env["mail.alias.domain"]._get_catchall_emails()

        email_to_list = [email_normalize(e) or e for e in email_split(msg_dict["to"])]
        if not catchall_aliases or not email_to_list:
            return False
        check = any if match_any else all
        return check(email_to in catchall_aliases for email_to in email_to_list)

    def _route_bounce_catchall(
        self, message: EmailMessage, message_dict: dict
    ) -> list[Route]:
        email_to_list = [
            email_normalize(email) or email for email in email_split(message_dict["to"])
        ]
        company = (
            self.env["mail.alias.domain"]._get_company_for_catchall_emails(
                email_to_list
            )
            or self.env.company
        )
        self_company = self.with_company(company)
        body = self_company.env["ir.qweb"]._render(
            "mail.mail_bounce_catchall",
            {
                "message": message_dict,
                "res_company": company,
            },
        )
        self_company._routing_create_bounce_email(
            message_dict["email_from"],
            body,
            message,
            references=self._routing_bounce_references(message_dict),
            reply_to=company.email,
        )
        return []

    @api.model
    def _routing_get_allowed_catchall_domains(self) -> list[str]:
        return list(self.env["mail.alias.domain"]._get_allowed_domains())

    @api.model
    def _routing_get_local_parts(
        self, emails: list[str], allowed_domains: list[str]
    ) -> list[str]:
        allowed = frozenset(allowed_domains)
        local_parts = []
        for email_address in emails:
            left, _at, domain = email_address.partition("@")
            if not left or not domain:
                continue
            if allowed and domain not in allowed:
                continue
            local_parts.append(left)
        return local_parts

    @api.model
    def _mail_find_referenced_message(self, message_dict: dict) -> MailMessage:
        MailMessage_ = self.env["mail.message"].sudo()
        in_reply_to = (message_dict.get("in_reply_to") or "").strip()
        if in_reply_to and not self._mail_is_force_new_message_id(in_reply_to):
            if parent := MailMessage_.search(
                [("message_id", "=", in_reply_to)], order="id DESC", limit=1
            ):
                return parent

        references = [
            reference.strip()
            for reference in unfold_references(message_dict.get("references"))
            if not self._mail_is_force_new_message_id(reference)
        ][-32:]
        if not references:
            return MailMessage_.browse()
        return MailMessage_.search(
            [("message_id", "in", references)], order="id DESC", limit=1
        )

    @api.model
    def _mail_is_force_new_message_id(self, message_id: str) -> bool:
        return "-odoo-reply_to@" in message_id

    @api.model
    def _routing_get_replied_message(self, message_dict: dict) -> MailMessage:
        return self._mail_find_referenced_message(message_dict)

    @api.model
    def _routing_get_other_model_aliases(
        self,
        reply_model: str,
        email_to_list: list[str],
        email_to_localparts: list[str],
    ) -> MailAlias:
        return self.env["mail.alias"].search(
            [
                "&",
                ("alias_model_id", "!=", self.env["ir.model"]._get_id(reply_model)),
                "|",
                ("alias_full_name", "in", email_to_list),
                "&",
                ("alias_name", "in", email_to_localparts),
                ("alias_incoming_local", "=", True),
            ],
            order="id",
        )

    @api.model
    def _routing_filter_alias_recipients(
        self, emails: list[str], aliases: MailAlias
    ) -> list[str]:
        full_names = frozenset(aliases.mapped("alias_full_name"))
        local_names = frozenset(
            aliases.filtered("alias_incoming_local").mapped("alias_name")
        )
        return [
            email_address
            for email_address in emails
            if email_address in full_names
            or email_address.split("@", 1)[0] in local_names
        ]

    @api.model
    def _routing_get_reply_aliases(
        self,
        reply_model: str,
        reply_thread_id: int | Literal[False],
        rcpt_tos_list: list[str],
        rcpt_tos_localparts: list[str],
    ) -> MailAlias:
        reply_model_id = self.env["ir.model"]._get_id(reply_model)
        dest_aliases = self.env["mail.alias"].search(
            [
                "&",
                ("alias_model_id", "=", reply_model_id),
                "|",
                ("alias_full_name", "in", rcpt_tos_list),
                "&",
                ("alias_name", "in", rcpt_tos_localparts),
                ("alias_incoming_local", "=", True),
            ],
            limit=1,
            order="id",
        )
        if dest_aliases or not reply_thread_id:
            return dest_aliases

        target_record = self.env[reply_model].sudo().browse(reply_thread_id).exists()
        if (
            target_record
            and "alias_id" in target_record._fields
            and target_record.alias_id
        ):
            return target_record.alias_id

        Alias = self.env["mail.alias"]
        model_domain = [("alias_model_id", "=", reply_model_id)]
        if Alias.search_count(
            [*model_domain, ("alias_contact", "=", "everyone")], limit=1
        ):
            return dest_aliases
        return Alias.search(model_domain, order="id", limit=1) or dest_aliases

    @api.model
    def _routing_get_alias_model(self, model: str) -> models.BaseModel:
        if model in self.env and self._mail_is_thread(self.env[model]):
            return self.env[model]
        return self

    @api.model
    def _routing_check_alias_routes(
        self,
        message: EmailMessage,
        message_dict: dict,
        dest_aliases: MailAlias,
        email_from: str,
    ) -> list[Route]:
        routes = []
        for alias in dest_aliases:
            user_id = (
                self._mail_find_user_for_gateway(email_from, alias=alias).id
                or self.env.uid
            )
            route = Route(
                alias.sudo().alias_model_id.model,
                alias.alias_force_thread_id,
                alias._get_alias_defaults(),
                user_id,
                alias,
            )
            route = self._routing_get_alias_model(route.model)._routing_check_route(
                message, message_dict, route, raise_exception=True
            )
            if isinstance(route, Route):
                _logger.info(
                    "Routing mail from %s to %s with Message-Id %s: direct alias match: %r",
                    email_from,
                    message_dict["to"],
                    message_dict["message_id"],
                    route,
                )
                routes.append(route)
        return routes

    @api.model
    def _routing_parse_recipients(
        self,
        message_dict: dict,
        catchall_domains_allowed: list[str],
        is_a_reply: bool,
        reply_model: str | Literal[False],
        reply_thread_id: int | Literal[False],
    ) -> tuple[RoutingRecipients, bool, str | Literal[False], int | Literal[False]]:
        email_to = [e.lower() for e in email_split(message_dict["to"])]
        email_to_localparts = self._routing_get_local_parts(
            email_to, catchall_domains_allowed
        )
        rcpt_tos = [e.lower() for e in email_split(message_dict["recipients"])]
        rcpt_tos_localparts = self._routing_get_local_parts(
            rcpt_tos, catchall_domains_allowed
        )
        rcpt_tos_valid = list(rcpt_tos)

        if reply_model and reply_thread_id:
            other_model_aliases = self._routing_get_other_model_aliases(
                reply_model, email_to, email_to_localparts
            )
            if other_model_aliases:
                is_a_reply, reply_model, reply_thread_id = False, False, False
                rcpt_tos_valid = self._routing_filter_alias_recipients(
                    rcpt_tos_valid, other_model_aliases
                )

        recipients = RoutingRecipients(
            email_to,
            email_to_localparts,
            rcpt_tos,
            rcpt_tos_localparts,
            rcpt_tos_valid,
            self._routing_get_local_parts(rcpt_tos_valid, catchall_domains_allowed),
        )
        return recipients, is_a_reply, reply_model, reply_thread_id

    @api.model
    def _routing_route_reply(
        self,
        message: EmailMessage,
        message_dict: dict,
        recipients: RoutingRecipients,
        reply_model: str,
        reply_thread_id: int | Literal[False],
        custom_values: dict | Literal[False] | None,
    ) -> list[Route] | None:
        email_from = message_dict["email_from"]
        dest_aliases = self._routing_get_reply_aliases(
            reply_model,
            reply_thread_id,
            recipients.rcpt_tos,
            recipients.rcpt_tos_localparts,
        )
        user_id = (
            self._mail_find_user_for_gateway(email_from, alias=dest_aliases).id
            or self.env.uid
        )
        route = self._routing_check_route(
            message,
            message_dict,
            Route(reply_model, reply_thread_id, None, user_id, dest_aliases),
            raise_exception=False,
        )
        if isinstance(route, Route):
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: direct reply to msg: model: %s, thread_id: %s, custom_values: %s, uid: %s",
                email_from,
                message_dict["to"],
                message_dict["message_id"],
                reply_model,
                reply_thread_id,
                None,
                self.env.uid,
            )
            return [route]
        if route is RouteVerdict.REFUSED:
            return []
        return None

    @api.model
    def _routing_route_aliases(
        self,
        message: EmailMessage,
        message_dict: dict,
        recipients: RoutingRecipients,
        catchall_aliases: list[str] | tuple[str, ...],
        email_from: str,
    ) -> list[Route] | None:
        message_dict.pop("parent_id", None)
        if self._detect_write_to_catchall(
            message_dict, catchall_aliases=catchall_aliases
        ):
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: direct write to catchall, bounce",
                email_from,
                message_dict["to"],
                message_dict["message_id"],
            )
            return self._route_bounce_catchall(message, message_dict)

        dest_aliases = self.env["mail.alias"].search(
            [
                "|",
                ("alias_full_name", "in", recipients.rcpt_tos_valid),
                "&",
                ("alias_name", "in", recipients.rcpt_tos_valid_localparts),
                ("alias_incoming_local", "=", True),
            ],
            order="id",
        )
        dest_aliases = self._routing_filter_local_aliases(
            dest_aliases, recipients.rcpt_tos_valid
        )
        if dest_aliases:
            return self._routing_check_alias_routes(
                message, message_dict, dest_aliases, email_from
            )
        return None

    @api.model
    def _routing_route_fallback(
        self,
        message: EmailMessage,
        message_dict: dict,
        fallback_model: str,
        thread_id: int | None,
        custom_values: dict | None,
        email_from: str,
    ) -> list[Route] | None:
        message_dict.pop("parent_id", None)
        user_id = self._mail_find_user_for_gateway(email_from).id or self.env.uid
        route = self._routing_check_route(
            message,
            message_dict,
            Route(fallback_model, thread_id, custom_values, user_id, None),
            raise_exception=True,
        )
        if isinstance(route, Route):
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: fallback to model:%s, thread_id:%s, custom_values:%s, uid:%s",
                email_from,
                message_dict["to"],
                message_dict["message_id"],
                fallback_model,
                thread_id,
                custom_values,
                user_id,
            )
            return [route]
        return None

    @api.model
    def message_route(
        self,
        message: EmailMessage,
        message_dict: dict,
        model: str | None = None,
        thread_id: int | Literal[False] | None = None,
        custom_values: dict | Literal[False] | None = None,
    ) -> list[Route]:
        if not isinstance(message, EmailMessage):
            raise TypeError(
                "message must be an email.message.EmailMessage at this point"
            )
        catchall_domains_allowed = self._routing_get_allowed_catchall_domains()
        fallback_model = model

        if message_dict.get("is_bounce"):
            self._routing_handle_bounce(message, message_dict)
            return []
        self._routing_reset_bounce(message, message_dict)

        replying_to_msg = self._routing_get_replied_message(message_dict)
        is_a_reply, reply_model, reply_thread_id = (
            bool(replying_to_msg),
            replying_to_msg.model,
            replying_to_msg.res_id,
        )

        email_from = message_dict["email_from"]
        recipients, is_a_reply, reply_model, reply_thread_id = (
            self._routing_parse_recipients(
                message_dict,
                catchall_domains_allowed,
                is_a_reply,
                reply_model,
                reply_thread_id,
            )
        )
        rcpt_tos_list = recipients.rcpt_tos

        if is_a_reply and reply_model:
            routes = self._routing_route_reply(
                message,
                message_dict,
                recipients,
                reply_model,
                reply_thread_id,
                custom_values,
            )
            if routes is not None:
                return routes

        catchall_aliases = self.env["mail.alias.domain"]._get_catchall_emails()
        if rcpt_tos_list:
            routes = self._routing_route_aliases(
                message, message_dict, recipients, catchall_aliases, email_from
            )
            if routes is not None:
                return routes

        if fallback_model:
            routes = self._routing_route_fallback(
                message,
                message_dict,
                fallback_model,
                thread_id,
                custom_values,
                email_from,
            )
            if routes is not None:
                return routes

        return self._routing_route_unclaimed(
            message, message_dict, recipients, catchall_aliases
        )

    @api.model
    def _routing_route_unclaimed(
        self,
        message: EmailMessage,
        message_dict: dict,
        recipients: RoutingRecipients,
        catchall_aliases: list[str] | tuple[str, ...],
    ) -> list[Route]:
        email_from = message_dict["email_from"]
        message_id = message_dict["message_id"]
        if recipients.rcpt_tos and self._detect_write_to_catchall(
            message_dict, catchall_aliases=catchall_aliases, match_any=True
        ):
            _logger.info(
                "Routing mail from %s to %s with Message-Id %s: write to catchall + other unroutable emails, bounce",
                email_from,
                message_dict["to"],
                message_id,
            )
            return self._route_bounce_catchall(message, message_dict)

        raise ValueError(
            "No possible route found for incoming message from %s to %s (Message-Id %s:). "
            "Create an appropriate mail.alias or force the destination model."
            % (email_from, message_dict["to"], message_id)
        )

    _GATEWAY_ONLY_MESSAGE_KEYS = (
        "from",
        "recipients",
        "cc",
        "to",
        "references",
        "in_reply_to",
        "x_odoo_message_id",
        "is_bounce",
        "bounced_email",
        "bounced_message",
        "bounced_msg_ids",
        "bounced_partner",
        "author_lookups",
    )

    @api.model
    def _message_route_process_document(
        self,
        message: EmailMessage,
        message_dict: dict,
        model: str,
        thread_id: int | Literal[False],
        custom_values: dict | None,
        user_id: int,
        alias: MailAlias | None,
    ) -> tuple[models.BaseModel, dict, int | Literal[False]]:
        related_user = self.env["res.users"].browse(user_id)
        Model = self.env[model].with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True
        )
        if not self._mail_is_thread(Model):
            raise ValueError(
                "Undeliverable mail with Message-Id %s, model %s does not accept incoming emails"
                % (message_dict["message_id"], model)
            )
        ModelCtx = Model
        if alias:
            if self.env.is_system():
                ModelCtx = Model.with_user(related_user)
            ModelCtx = ModelCtx.sudo()
        if thread_id:
            thread = ModelCtx.browse(thread_id)
            thread.message_update(message_dict)
            return thread, message_dict, False

        route_message_dict = {
            key: value for key, value in message_dict.items() if key != "parent_id"
        }
        try:
            thread = ModelCtx.message_new(route_message_dict, custom_values)
        except Exception:
            if alias:
                self._routing_bounce_failed_creation(alias, message, message_dict)
            raise
        if alias:
            alias._alias_mark_valid()
        return thread, route_message_dict, thread._creation_subtype().id

    @api.model
    def _routing_bounce_failed_creation(
        self, alias: MailAlias, message: EmailMessage, message_dict: dict
    ) -> None:
        with self.pool.cursor() as new_cr:
            bounce_env = self.env(cr=new_cr)
            bounce_alias = bounce_env["mail.alias"].browse(alias.id)
            if bounce_alias.exists() and bounce_alias.alias_status == "invalid":
                _logger.info(
                    "Routing mail with Message-Id %s: alias %s is already recorded "
                    "invalid; not bouncing again for the same breakage.",
                    message_dict["message_id"],
                    bounce_alias.alias_full_name,
                )
                return
            bounce_env["mixin.mail.gateway"]._routing_bounce_alias(
                bounce_alias, message, message_dict, is_config_error=True
            )

    @api.model
    def _message_route_post_params(
        self,
        route_message_dict: dict,
        *,
        incoming_email_to: str | Literal[False],
        incoming_email_cc: str | Literal[False],
        subtype_id: int | Literal[False],
        partner_ids: list[int],
    ) -> dict:
        post_params = {
            key: value
            for key, value in route_message_dict.items()
            if key not in self._GATEWAY_ONLY_MESSAGE_KEYS
        }
        computed = {
            "incoming_email_cc": incoming_email_cc,
            "incoming_email_to": incoming_email_to,
            "subtype_id": subtype_id,
            "partner_ids": partner_ids,
        }
        if clashing := post_params.keys() & computed.keys():
            raise ValueError(
                "The gateway computes %s for message %s, and the parsed message "
                "already carries it. One of the two is wrong; they cannot both "
                "reach message_post."
                % (
                    ", ".join(sorted(clashing)),
                    route_message_dict.get("message_id"),
                )
            )
        return post_params | computed

    @api.model
    def _message_route_subtype_and_recipients(
        self, route_message_dict: dict, creation_subtype_id: int | Literal[False]
    ) -> tuple[int, list[int]]:
        subtype_id = creation_subtype_id
        if not subtype_id:
            xmlid = (
                "mail.mt_note"
                if route_message_dict.get("is_internal")
                else "mail.mt_comment"
            )
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(xmlid)

        parent_id = route_message_dict.get("parent_id")
        if not parent_id:
            return subtype_id, []
        parent_message = self.env["mail.message"].sudo().browse(parent_id)
        author = parent_message.author_id
        if author and (route_message_dict.get("is_internal") or author.partner_share):
            return subtype_id, [author.id]
        return subtype_id, []

    @api.model
    def _message_route_process(
        self, message: EmailMessage, message_dict: dict, routes: list[Route]
    ) -> int | Literal[False]:
        self = self.with_context(attachments_mime_plainxml=True)
        original_partner_ids = message_dict.pop("partner_ids", [])
        incoming_email_cc = message_dict.pop("cc_filtered", False)
        incoming_email_to = message_dict.pop("to_filtered", False)
        root_user = self.env.ref("base.user_root")
        thread_id = False
        for route in routes or ():
            route = Route(*route)
            thread, route_message_dict, creation_subtype_id = (
                self._message_route_process_document(
                    message,
                    message_dict,
                    route.model,
                    route.thread_id,
                    route.custom_values,
                    route.uid,
                    route.alias,
                )
            )
            thread_id = thread.id
            thread_root = thread.with_user(root_user)
            subtype_id, partner_ids = self._message_route_subtype_and_recipients(
                route_message_dict, creation_subtype_id
            )

            post_params = self._message_route_post_params(
                route_message_dict,
                incoming_email_to=incoming_email_to,
                incoming_email_cc=incoming_email_cc,
                subtype_id=subtype_id,
                partner_ids=partner_ids,
            )
            new_msg = False
            if thread_root._name == "mixin.mail.thread":
                new_msg = thread_root.message_notify(**post_params)
            else:
                thread_root = thread_root.with_context(
                    mail_post_autofollow_author_skip=not route_message_dict.get(
                        "author_id"
                    )
                )
                new_msg = thread_root.message_post(**post_params)

            if new_msg and original_partner_ids:
                new_msg.write({"partner_ids": original_partner_ids})
        return thread_id

    @api.model
    def message_process(
        self,
        model: str,
        message: xmlrpclib.Binary | str | bytes,
        custom_values: dict | None = None,
        save_original: bool = False,
        strip_attachments: bool = False,
        thread_id: int | None = None,
    ) -> int | Literal[False] | None:
        if isinstance(message, xmlrpclib.Binary):
            message = bytes(message.data)
        if isinstance(message, str):
            message = message.encode("utf-8")
        message = email.message_from_bytes(message, policy=email.policy.SMTP)

        msg_dict = self.message_parse(message, save_original=save_original)
        if strip_attachments:
            msg_dict.pop("attachments", None)

        msg_id = msg_dict.get("message_id")
        is_duplicate = bool(
            self.env["mail.message"]
            .sudo()
            .search_count([("message_id", "=", msg_id)], limit=1)
        )
        if not is_duplicate and msg_id:
            self.env.cr.execute(
                SQL("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", msg_id)
            )
            is_duplicate = not self.env.cr.fetchone()[0]

        if is_duplicate:
            _logger.info(
                "Ignored mail from %s to %s with Message-Id %s: found duplicated Message-Id during processing",
                msg_dict.get("email_from"),
                msg_dict.get("to"),
                msg_id,
            )
            return False

        if self._detect_loop_headers(msg_dict):
            _logger.info(
                "Ignored mail from %s to %s with Message-Id %s: reply to a bounce notification detected by headers",
                msg_dict.get("email_from"),
                msg_dict.get("to"),
                msg_dict.get("message_id"),
            )
            return None

        routes = self.message_route(message, msg_dict, model, thread_id, custom_values)
        if self._detect_loop_sender(message, msg_dict, routes):
            return None

        msg_dict.update(**self._message_parse_post_process(message, msg_dict, routes))

        return self._message_route_process(message, msg_dict, routes)

    def _message_receive_bounce(self, email: str, partner: ResPartner) -> None:
        pass

    def _message_reset_bounce(self, email: str) -> None:
        pass

    def _message_parse_extract_payload_postprocess(
        self, message: EmailMessage, payload_dict: dict
    ) -> dict:
        payload = mime.postprocess_payload(
            mime.Payload(payload_dict["body"], payload_dict["attachments"])
        )
        return {"body": payload.body, "attachments": payload.attachments}

    def _message_parse_repair_part_headers(self, part: EmailMessage) -> None:
        mime.repair_part_headers(part)

    def _message_parse_extract_payload(
        self, message: EmailMessage, message_dict: dict, save_original: bool = False
    ) -> dict:
        payload = mime.extract_payload(
            message,
            is_bounce=bool(message_dict.get("is_bounce")),
            save_original=save_original,
        )
        return self._message_parse_extract_payload_postprocess(
            message, {"body": payload.body, "attachments": payload.attachments}
        )

    def _message_parse_bounce_find_part(
        self, email_message: EmailMessage, content_types: tuple[str, ...]
    ) -> EmailMessage | None:
        return mime.find_part(email_message, content_types)

    def _message_parse_bounce_recipient(
        self, dsn_part: EmailMessage | None
    ) -> tuple[str | Literal[False], ResPartner]:
        void = self.env["res.partner"].sudo()
        payload = dsn_part.get_payload() if dsn_part else None
        if not isinstance(payload, list) or len(payload) <= 1:
            return False, void
        final_recipient = decode_message_header(payload[1], "Final-Recipient")
        if not final_recipient or ";" not in final_recipient:
            return False, void
        bounced_email = email_normalize(final_recipient.split(";", 1)[1].strip())
        if not bounced_email:
            return False, void
        return bounced_email, void.search([("email_normalized", "=", bounced_email)])

    def _message_parse_extract_bounce(
        self, email_message: EmailMessage, message_dict: dict
    ) -> dict:
        if not isinstance(email_message, EmailMessage):
            raise TypeError(
                "message must be an email.message.EmailMessage at this point"
            )

        is_bounce = self._detect_is_bounce(email_message, message_dict)
        if not is_bounce:
            return {"is_bounce": False}

        email_part = self._message_parse_bounce_find_part(
            email_message, ("message/rfc822", "text/rfc822-headers")
        ) or self._message_parse_bounce_find_part(email_message, ("multipart/report",))
        dsn_part = self._message_parse_bounce_find_part(
            email_message, ("message/delivery-status",)
        )
        bounced_email, bounced_partner = self._message_parse_bounce_recipient(dsn_part)

        bounced_msg_ids = False
        bounced_message = self.env["mail.message"].sudo()
        if email_part:
            if email_part.get_content_type() == "text/rfc822-headers":
                email_payload = message_from_string(
                    mime.part_content(email_part), policy=email.policy.SMTP
                )
            else:
                payload = email_part.get_payload()
                email_payload = (
                    payload[0] if isinstance(payload, list) and payload else None
                )
            if email_payload is not None:
                bounced_message, bounced_msg_ids = self._get_bounced_message_data(
                    email_payload, message_dict
                )

        if (
            bounced_message
            and not bounced_partner
            and len(bounced_message.notification_ids.res_partner_id) == 1
        ):
            bounced_partner = bounced_message.notification_ids.res_partner_id[0]
            bounced_email = bounced_partner.email_normalized or email_normalize(
                bounced_partner.email
            )

        return {
            "bounced_email": bounced_email,
            "bounced_partner": bounced_partner,
            "bounced_msg_ids": bounced_msg_ids,
            "bounced_message": bounced_message,
            "is_bounce": True,
        }

    @api.model
    def message_parse(self, message: EmailMessage, save_original: bool = False) -> dict:
        if not isinstance(message, EmailMessage):
            raise ValueError("Message should be a valid EmailMessage instance")
        msg_dict = {"message_type": "email"}

        message_id = message.get("Message-Id")
        if not message_id:
            message_id = "<%s@localhost>" % time.time()
            _logger.debug(
                "Parsing Message without message-id, generating a random one: %s",
                message_id,
            )
        msg_dict["message_id"] = message_id.strip()

        if message.get("Subject"):
            msg_dict["subject"] = decode_message_header(message, "Subject")

        email_from = decode_message_header(message, "From", separator=",")
        email_cc = decode_message_header(message, "cc", separator=",")
        email_from_list = email_split_and_format(email_from)
        email_cc_list = email_split_and_format(email_cc)
        msg_dict["email_from"] = email_from_list[0] if email_from_list else email_from
        msg_dict["from"] = msg_dict["email_from"]
        msg_dict["cc"] = ",".join(email_cc_list) if email_cc_list else email_cc
        email_to_list = _dedup_ordered(
            _headers_to_emails(message, ("Delivered-To", "To"))
        )
        msg_dict["recipients"] = ",".join(
            _dedup_ordered(
                email_to_list
                + _headers_to_emails(message, ("Cc", "Resent-To", "Resent-Cc"))
            )
        )
        msg_dict["to"] = ",".join(email_to_list)
        recipients_normalized_all = email_normalize_all(
            f"{msg_dict['to']},{msg_dict['cc']}"
        )
        alias_emails = (
            self.env["mail.alias.domain"]
            .sudo()
            ._find_aliases(recipients_normalized_all)
        )
        msg_dict["cc_filtered"] = ",".join(
            cc for cc in email_cc_list if email_normalize(cc) not in alias_emails
        )
        msg_dict["to_filtered"] = ",".join(
            to for to in email_to_list if email_normalize(to) not in alias_emails
        )

        msg_dict["references"] = decode_message_header(message, "References")
        msg_dict["in_reply_to"] = decode_message_header(message, "In-Reply-To").strip()

        if message.get("Date"):
            try:
                date_hdr = decode_message_header(message, "Date")
                parsed_date = dateutil.parser.parse(date_hdr, fuzzy=True)
                if parsed_date.utcoffset() is None:
                    stored_date = parsed_date.replace(tzinfo=UTC)
                else:
                    stored_date = parsed_date.astimezone(tz=UTC)
            except Exception:
                _logger.info(
                    "Failed to parse Date header %r in incoming mail "
                    "with message-id %r, assuming current date/time.",
                    message.get("Date"),
                    message_id,
                )
                stored_date = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            msg_dict["date"] = fields.Datetime.to_string(stored_date)

        msg_dict.update(
            self._message_parse_extract_from_parent(self._get_parent_message(msg_dict))
        )
        msg_dict.update(self._message_parse_extract_bounce(message, msg_dict))
        msg_dict.update(
            self._message_parse_extract_payload(
                message, msg_dict, save_original=save_original
            )
        )
        return msg_dict

    def _message_parse_extract_from_parent(
        self, parent_message: MailMessage | None
    ) -> dict:
        if parent_message:
            parent_is_internal = bool(
                parent_message.subtype_id and parent_message.subtype_id.internal
            )
            parent_is_auto_comment = parent_message.message_type == "auto_comment"
            return {
                "parent_id": parent_message.id,
                "is_internal": parent_is_internal and not parent_is_auto_comment,
            }
        return {}

    def _message_parse_post_process(
        self, message: EmailMessage, message_dict: dict, routes: list[Route]
    ) -> dict:
        values = {
            "author_id": message_dict.get("author_id"),
            "partner_ids": message_dict.get("partner_ids"),
        }
        for model, thread_id, _custom_values, _user_id, alias in routes or ():
            link_doc = self._routing_link_document(
                self.env[model].browse(thread_id) if thread_id else self.env[model],
                alias,
            )
            if not values.get("author_id"):
                author = self._routing_find_author(message_dict, link_doc)
                if author:
                    values["author_id"] = author.id
            if not values.get("partner_ids") and message_dict["recipients"]:
                values["partner_ids"] = link_doc._partner_find_from_emails_single(
                    email_split(message_dict["recipients"]), no_create=True
                ).ids
        return values

    def _get_bounced_message_data(
        self, message: EmailMessage, message_dict: dict
    ) -> tuple[MailMessage, list[str]]:
        reference_ids = []
        headers = ("Message-Id", "X-Microsoft-Original-Message-ID")
        for header in headers:
            value = decode_message_header(message, header)
            references = unfold_references(value)
            reference_ids.extend([reference.strip() for reference in references])

        if reference_ids:
            bounced_message = (
                self.env["mail.message"]
                .sudo()
                .search(
                    [("message_id", "in", reference_ids)],
                    order="create_date DESC, id DESC",
                    limit=1,
                )
            )

            if bounced_message:
                return bounced_message, reference_ids

        reference_ids.extend(unfold_references(message_dict["in_reply_to"]))
        reference_ids.extend(
            [r.strip() for r in unfold_references(message_dict["references"])]
        )

        if message_dict.get("parent_id"):
            bounced_message = self.env["mail.message"].browse(message_dict["parent_id"])
            return bounced_message, reference_ids

        return self.env["mail.message"], reference_ids

    def _get_parent_message(self, msg_dict: dict) -> MailMessage | None:
        return self._mail_find_referenced_message(msg_dict) or None

    def _mail_find_user_for_gateway(
        self, email_value: str, alias: MailAlias | None = None
    ) -> ResUsers:
        normalized_email = email_normalize(email_value)
        if not normalized_email:
            return self.env["res.users"]

        record_su = self.env["mixin.mail.thread"].sudo()
        if alias and alias.alias_parent_model_id and alias.alias_parent_thread_id:
            record_su = (
                self.env[alias.alias_parent_model_id.sudo().model]
                .browse(alias.alias_parent_thread_id)
                .sudo()
            )
            record_su = (
                record_su
                if self._mail_is_thread(record_su)
                else self.env["mixin.mail.thread"].sudo()
            )

        partner = record_su._partner_find_from_emails_single(
            [email_value], filter_found=lambda p: p.user_ids, no_create=True
        )
        return partner.main_user_id
