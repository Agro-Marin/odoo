import ast
import base64
import datetime
import email
import email.policy
import hashlib
import hmac
import json
import logging
import time
import typing
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from datetime import UTC
from email import message_from_string
from email.message import EmailMessage
from itertools import batched
from types import NotImplementedType
from typing import Any, Literal, NamedTuple, Self
from urllib.parse import urlencode
from xmlrpc import client as xmlrpclib

import dateutil
import lxml
from lxml import etree, html
from markupsafe import Markup, escape
from requests import Session

from odoo import _, api, exceptions, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, MissingError
from odoo.fields import Domain
from odoo.tools import (
    SQL,
    clean_context,
    html2plaintext,
    html_escape,
    is_html_empty,
    is_list_of,
    ormcache,
)
from odoo.tools.mail import (
    append_content_to_html,
    decode_message_header,
    email_normalize,
    email_normalize_all,
    email_split,
    email_split_and_format,
    email_split_and_format_normalize,
    email_split_and_normalize,
    formataddr,
    generate_tracking_message_id,
    html_sanitize,
    unfold_references,
)

from odoo.addons.mail.tools.discuss import Store, StoreFieldsInput, StoreFieldSpec
from odoo.addons.mail.tools.web_push import (
    ENCRYPTION_BLOCK_OVERHEAD,
    ENCRYPTION_HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    DeviceUnreachableError,
    PushEndpointUnresolvableError,
    push_to_end_point,
)

if typing.TYPE_CHECKING:
    from .mail_alias import MailAlias
    from .mail_followers import MailFollowers
    from .mail_mail import MailMail
    from .mail_message import MailMessage
    from .mail_message_subtype import MailMessageSubtype
    from .mail_push_device import MailPushDevice
    from .mail_template import MailTemplate
    from .mail_tracking_value import MailTrackingValue
    from .res_company import ResCompany
    from .res_partner import ResPartner
    from odoo.addons.bus.models.ir_attachment import IrAttachment
    from odoo.addons.bus.models.res_users import ResUsers


class Route(NamedTuple):
    model: str
    thread_id: int | None
    custom_values: dict | None
    uid: int
    alias: MailAlias | None


class Attachment(NamedTuple):
    fname: str
    content: str | bytes | EmailMessage | None
    info: dict


MAX_DIRECT_PUSH = 5
BAD_CONTENT_TYPES = (
    "binary/octet-stream",
    "*/*",
    "bin/plain",
)

_logger = logging.getLogger(__name__)


def _escape_body(body: str | Literal[False] | None) -> str:
    if body is None or body is False:
        return ""
    return escape(body)


def _dedup_ordered(emails: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(emails))


def _headers_to_emails(message: EmailMessage, headers: Iterable[str]) -> list[str]:
    return [
        formatted_email
        for header in headers
        if (address := decode_message_header(message, header, separator=","))
        for formatted_email in email_split_and_format(address)
    ]


def _email_part_get_content_safe(part: EmailMessage) -> str:
    try:
        return part.get_content()
    except LookupError, UnicodeDecodeError, ValueError:
        _logger.warning(
            "Unresolvable charset %r on inbound mail part; decoding as utf-8 "
            "with replacement.",
            part.get_content_charset(),
        )
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


class MailThread(models.AbstractModel):
    _name = "mail.thread"
    _description = "Email Thread"
    _mail_flat_thread = True
    _mail_thread_customer = False
    _mail_post_access = "write"
    _primary_email = "email"

    _CUSTOMER_HEADERS_LIMIT_COUNT = 50
    _FOLLOWER_PAGE_LIMIT = 100

    _Attachment = Attachment

    message_is_follower = fields.Boolean(
        "Is Follower",
        compute="_compute_message_is_follower",
        search="_search_message_is_follower",
    )
    message_follower_ids: MailFollowers = fields.One2many(
        "mail.followers", "res_id", string="Followers", groups="base.group_user"
    )
    message_partner_ids: ResPartner = fields.Many2many(
        comodel_name="res.partner",
        string="Followers (Partners)",
        compute="_compute_message_partner_ids",
        inverse="_inverse_message_partner_ids",
        search="_search_message_partner_ids",
        groups="base.group_user",
    )
    message_ids: MailMessage = fields.One2many(
        "mail.message",
        "res_id",
        string="Messages",
        domain=lambda self: [("message_type", "!=", "user_notification")],
        bypass_search_access=True,
    )
    has_message = fields.Boolean(
        compute="_compute_has_message", search="_search_has_message", store=False
    )
    message_needaction = fields.Boolean(
        "Action Needed",
        compute="_compute_message_needaction",
        search="_search_message_needaction",
        help="If checked, new messages require your attention.",
    )
    message_needaction_counter = fields.Integer(
        "Number of Actions",
        compute="_compute_message_needaction",
        help="Number of messages requiring action",
    )
    message_has_error = fields.Boolean(
        "Message Delivery error",
        compute="_compute_message_has_error",
        search="_search_message_has_error",
        help="If checked, some messages have a delivery error.",
    )
    message_has_error_counter = fields.Integer(
        "Number of errors",
        compute="_compute_message_has_error",
        help="Number of messages with delivery error",
    )
    message_attachment_count = fields.Integer(
        "Attachment Count",
        compute="_compute_message_attachment_count",
        groups="base.group_user",
    )

    @api.depends("message_follower_ids")
    def _compute_message_partner_ids(self) -> None:
        for thread in self:
            thread.message_partner_ids = thread.message_follower_ids.mapped(
                "partner_id"
            )

    def _inverse_message_partner_ids(self) -> None:
        to_unsubscribe = []

        for thread in self:
            new_partners_ids = thread.message_partner_ids
            previous_partners_ids = thread.message_follower_ids.partner_id
            removed_partners_ids = previous_partners_ids - new_partners_ids
            added_patners_ids = new_partners_ids - previous_partners_ids
            if added_patners_ids:
                thread.message_subscribe(added_patners_ids.ids)
            if removed_partners_ids:
                to_unsubscribe.append((thread, removed_partners_ids.ids))

        for thread, partner_ids in to_unsubscribe:
            thread.message_unsubscribe(partner_ids)

    @api.model
    def _search_message_partner_ids(
        self, operator: str, operand: Any
    ) -> list | NotImplementedType:
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        if not (self.env.su or self.env.user._is_internal()):
            user_partner = self.env.user.partner_id
            allow_partner_ids = set(
                (user_partner | user_partner.commercial_partner_id).ids
            )
            operand_values = (
                operand
                if isinstance(operand, Iterable) and not isinstance(operand, str)
                else [operand]
            )
            if not allow_partner_ids.issuperset(operand_values):
                raise AccessError(
                    self.env._(
                        "Portal users can only filter threads by themselves as followers."
                    )
                )

        followers = (
            self.env["mail.followers"]
            .sudo()
            ._search(
                [
                    ("res_model", "=", self._name),
                    ("partner_id", operator, operand),
                ]
            )
        )
        return [("id", "in", followers.subselect("res_id"))]

    @api.depends("message_follower_ids")
    def _compute_message_is_follower(self) -> None:
        followers = (
            self.env["mail.followers"]
            .sudo()
            .search_fetch(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "in", self.ids),
                    ("partner_id", "=", self.env.user.partner_id.id),
                ],
                ["res_id"],
            )
        )
        following_ids = set(followers.mapped("res_id"))
        for record in self:
            record.message_is_follower = record.id in following_ids

    @api.model
    def _search_message_is_follower(
        self, operator: str, operand: Any
    ) -> list | NotImplementedType:
        if operator != "in":
            return NotImplemented
        followers = (
            self.env["mail.followers"]
            .sudo()
            ._search(
                [
                    ("res_model", "=", self._name),
                    ("partner_id", operator, self.env.user.partner_id.ids),
                ]
            )
        )
        return [("id", "in", followers.subselect("res_id"))]

    def _compute_has_message(self) -> None:
        self.env["mail.message"].flush_model()
        self.env.cr.execute(
            """
            SELECT distinct res_id
              FROM mail_message mm
             WHERE res_id = any(%s)
               AND mm.model=%s
        """,
            [self.ids, self._name],
        )
        ids_with_message = {row[0] for row in self.env.cr.fetchall()}
        for record in self:
            record.has_message = record.id in ids_with_message

    def _search_has_message(
        self, operator: str, value: Any
    ) -> list | NotImplementedType:
        if operator != "in":
            return NotImplemented
        return [
            (
                "id",
                "in",
                SQL("(SELECT res_id FROM mail_message WHERE model = %s)", self._name),
            )
        ]

    def _compute_message_needaction(self) -> None:
        res = dict.fromkeys(self.ids, 0)
        if self.ids:
            self.env["mail.message"].flush_model(["model", "res_id", "message_type"])
            self.env["mail.notification"].flush_model(
                ["mail_message_id", "res_partner_id", "is_read"]
            )
            self.env.cr.execute(
                """
                    SELECT msg.res_id, COUNT(*)
                      FROM mail_message msg
                INNER JOIN mail_notification rel
                        ON rel.mail_message_id = msg.id
                     WHERE rel.res_partner_id = %(partner_id)s
                       AND COALESCE(rel.is_read, FALSE) = FALSE
                       AND msg.model = %(model_name)s
                       AND msg.res_id = ANY(%(res_ids)s)
                       AND msg.message_type != 'user_notification'
                  GROUP BY msg.res_id
            """,
                {
                    "partner_id": self.env.user.partner_id.id,
                    "model_name": self._name,
                    "res_ids": list(self.ids),
                },
            )
            res.update(self.env.cr.fetchall())

        for record in self:
            record.message_needaction_counter = res.get(record._origin.id, 0)
            record.message_needaction = bool(record.message_needaction_counter)

    @api.model
    def _search_message_needaction(
        self, operator: str, operand: Any
    ) -> list | NotImplementedType:
        if operator != "in":
            return NotImplemented
        return [("message_ids.needaction", operator, operand)]

    def _compute_message_has_error(self) -> None:
        res = {}
        if self.ids:
            self.env["mail.message"].flush_model(["model", "res_id", "message_type"])
            self.env["mail.notification"].flush_model(
                ["mail_message_id", "author_id", "notification_status"]
            )
            self.env.cr.execute(
                """
                    SELECT msg.res_id, COUNT(msg.res_id)
                      FROM mail_message msg
                INNER JOIN mail_notification notif
                        ON notif.mail_message_id = msg.id
                     WHERE notif.notification_status in ('exception', 'bounce')
                       AND notif.author_id = %(author_id)s
                       AND msg.model = %(model_name)s
                       AND msg.res_id = ANY(%(res_ids)s)
                       AND msg.message_type != 'user_notification'
                  GROUP BY msg.res_id
            """,
                {
                    "author_id": self.env.user.partner_id.id,
                    "model_name": self._name,
                    "res_ids": list(self.ids),
                },
            )
            res.update(self.env.cr.fetchall())

        for record in self:
            record.message_has_error_counter = res.get(record._origin.id, 0)
            record.message_has_error = bool(record.message_has_error_counter)

    @api.model
    def _search_message_has_error(
        self, operator: str, operand: Any
    ) -> list | NotImplementedType:
        if operator != "in":
            return NotImplemented
        message_domain = [
            ("has_error", "=", True),
            ("author_id", "=", self.env.user.partner_id.id),
        ]
        return [("message_ids", "any", message_domain)]

    def _compute_message_attachment_count(self) -> None:
        read_group_var = self.env["ir.attachment"]._read_group(
            [("res_id", "in", self._origin.ids), ("res_model", "=", self._name)],
            groupby=["res_id"],
            aggregates=["__count"],
        )

        attachment_count_dict = dict(read_group_var)
        for record in self:
            record.message_attachment_count = attachment_count_dict.get(
                record._origin.id, 0
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        if (
            self.env.context.get("mail_create_nosubscribe")
            and "mail_post_autofollow_author_skip" not in self.env.context
        ):
            self = self.with_context(mail_post_autofollow_author_skip=True)

        if self.env.context.get("tracking_disable"):
            threads = super().create(vals_list)
            threads._track_discard()
            return threads

        threads = super().create(vals_list)
        if (
            not self.env.context.get("mail_create_nosubscribe")
            and threads
            and self.env.user.active
            and not self.env.user.share
        ):
            self.env["mail.followers"]._add_followers(
                threads._name,
                threads.ids,
                self.env.user.partner_id.ids,
                subtypes=None,
                customer_ids=[],
                check_existing=False,
            )

        create_values_list = {}
        for thread, values in zip(threads, vals_list, strict=True):
            create_values = dict(values)
            for key, val in self.env.context.items():
                if key.startswith("default_") and key[8:] not in create_values:
                    create_values[key[8:]] = val
            create_values_list[thread.id] = create_values
        threads._message_auto_subscribe_batch(
            create_values_list, followers_existing_policy="update"
        )

        if not self.env.context.get("mail_create_nolog"):
            threads_no_subtype = self.env[self._name]
            for thread in threads:
                subtype = thread._creation_subtype()
                if not subtype:
                    threads_no_subtype += thread
                    continue
                thread.sudo().message_post(
                    subtype_id=subtype.id,
                    author_id=self.env.user.partner_id.id,
                    body=Markup('<div summary="o_mail_notification"><p>%s</p></div>')
                    % thread._creation_message(),
                )
            if threads_no_subtype:
                bodies = {
                    thread.id: thread._creation_message()
                    for thread in threads_no_subtype
                }
                threads_no_subtype._message_log_batch(bodies=bodies)

        threads._track_discard()
        if not self.env.context.get("mail_notrack"):
            fnames = self._track_get_fields()
            for thread in threads:
                create_values = create_values_list[thread.id]
                changes = [fname for fname in fnames if create_values.get(fname)]
                if changes:
                    self.env.cr.precommit.add(thread._track_post_template_finalize)
                    self.env.cr.precommit.data.setdefault(
                        f"mail.tracking.create.{self._name}.{thread.id}", changes
                    )
        return threads

    def write(self, vals: ValuesType) -> Literal[True]:
        if self.env.context.get("tracking_disable"):
            return super().write(vals)

        if not self.env.context.get("mail_notrack"):
            self._track_prepare(self._fields)

        result = super().write(vals)

        self._message_auto_subscribe(vals)

        return result

    def unlink(self) -> Literal[True]:
        if not self:
            return True
        self._track_discard()
        self.env["mail.message"].sudo().search(
            [("model", "=", self._name), ("res_id", "in", self.ids)]
        ).unlink()
        self.env["mail.followers"].sudo().search(
            [("res_model", "=", self._name), ("res_id", "in", self.ids)]
        ).unlink()
        self.env["mail.scheduled.message"].sudo().search(
            [("model", "=", self._name), ("res_id", "in", self.ids)]
        ).unlink()
        return super().unlink()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        return super(MailThread, self.with_context(mail_notrack=True)).copy_data(
            default=default
        )

    @api.model
    def get_empty_list_help(self, help_message: str) -> str:
        model = self.env.context.get("empty_list_help_model")
        res_id = self.env.context.get("empty_list_help_id")
        document_name = self.env.context.get(
            "empty_list_help_document_name", _("document")
        )
        nothing_here = is_html_empty(help_message)
        alias = None

        if model and res_id:
            record = self.env[model].sudo().browse(res_id)
            if (
                "alias_id" in record
                and record.alias_id
                and record.alias_id.alias_name
                and record.alias_id.alias_domain
                and record.alias_id.alias_model_id.model == self._name
                and record.alias_id.alias_force_thread_id == 0
            ):
                alias = record.alias_id
        if not alias and model and self.env.company.alias_domain_id:
            aliases = self.env["mail.alias"].search(
                [
                    ("alias_domain_id", "=", self.env.company.alias_domain_id.id),
                    ("alias_parent_model_id.model", "=", model),
                    ("alias_name", "!=", False),
                    ("alias_force_thread_id", "=", False),
                    ("alias_parent_thread_id", "=", False),
                ],
                order="id ASC",
                limit=2,
            )
            if len(aliases) == 1:
                alias = aliases[0]

        if alias:
            email_link = Markup("<a href='mailto:%s'>%s</a>") % (
                alias.display_name,
                alias.display_name,
            )
            if nothing_here:
                dyn_help = _(
                    "Add a new %(document)s or send an email to %(email_link)s",
                    document=html_escape(document_name),
                    email_link=email_link,
                )
                return super().get_empty_list_help(
                    f"<p class='o_view_nocontent_smiling_face'>{dyn_help}</p>"
                )
            if "oe_view_nocontent_alias" not in help_message:
                dyn_help = _(
                    "Create new %(document)s by sending an email to %(email_link)s",
                    document=html_escape(document_name),
                    email_link=email_link,
                )
                return super().get_empty_list_help(
                    f"{help_message}<p class='oe_view_nocontent_alias'>{dyn_help}</p>"
                )

        if nothing_here:
            dyn_help = _("Create new %(document)s", document=html_escape(document_name))
            return super().get_empty_list_help(
                f"<p class='o_view_nocontent_smiling_face'>{dyn_help}</p>"
            )

        return super().get_empty_list_help(help_message)

    @api.model
    def get_views(
        self, views: list[list[int | str]], options: dict | None = None
    ) -> dict:
        res = super().get_views(views, options)
        if "form" in res["views"] and isinstance(
            self.env[self._name], self.env.registry["mail.activity.mixin"]
        ):
            res["models"][self._name]["has_activities"] = True
        return res

    def _compute_field_value(self, field: fields.Field) -> None:
        if not self.env.context.get("tracking_disable") and not self.env.context.get(
            "mail_notrack"
        ):
            self._track_prepare(
                f.name for f in self.pool.field_computed[field] if f.store
            )

        return super()._compute_field_value(field)

    def _creation_subtype(self) -> MailMessageSubtype:
        return self.env["mail.message.subtype"]

    def _creation_message(self) -> str:
        self.ensure_one()
        doc_name = self.env["ir.model"]._get(self._name).name
        return _("%s created", doc_name)

    def _valid_field_parameter(self, field: fields.Field, name: str) -> bool:
        return name == "tracking" or super()._valid_field_parameter(field, name)

    def _mail_is_thread(self, record_or_model: models.BaseModel) -> bool:
        return isinstance(record_or_model, self.pool["mail.thread"])

    def _fallback_lang(self) -> Self:
        if not self.env.context.get("lang"):
            return self.with_context(lang=self.env.user.lang)
        return self

    def _check_can_update_message_content(self, messages: MailMessage) -> None:
        if messages.tracking_value_ids:
            raise exceptions.UserError(
                _("Messages with tracking values cannot be modified")
            )
        if any(message.message_type != "comment" for message in messages):
            raise exceptions.UserError(
                _("Only messages type comment can have their content updated")
            )

    def _track_prepare(self, fields_iter: Iterable[str]) -> None:
        fnames = self._track_get_fields().intersection(fields_iter)
        if not fnames:
            return
        self.env.cr.precommit.add(self._track_finalize)
        initial_values = self.env.cr.precommit.data.setdefault(
            f"mail.tracking.{self._name}", {}
        )
        writer_uids = self.env.cr.precommit.data.setdefault(
            f"mail.tracking.uid.{self._name}", {}
        )
        for record in self:
            if not record.id:
                continue
            writer_uids.setdefault(record.id, self.env.uid)
            values = initial_values.setdefault(record.id, {})
            if values is not None:
                for fname in fnames:
                    value = (
                        field.convert_to_read(record[fname], record)
                        if (field := record._fields[fname]).type == "properties"
                        else record[fname]
                    )
                    values.setdefault(fname, value)

    def _track_discard(self) -> None:
        if not self._track_get_fields():
            return
        self.env.cr.precommit.add(self._track_finalize)
        initial_values = self.env.cr.precommit.data.setdefault(
            f"mail.tracking.{self._name}", {}
        )
        for id_ in self.ids:
            initial_values[id_] = None

    def _track_filter_for_display(
        self, tracking_values: MailTrackingValue
    ) -> MailTrackingValue:
        self.ensure_one()
        return tracking_values

    def _track_finalize(self) -> None:
        initial_values = self.env.cr.precommit.data.pop(
            f"mail.tracking.{self._name}", {}
        )
        writer_uids = self.env.cr.precommit.data.pop(
            f"mail.tracking.uid.{self._name}", {}
        )
        ids = [id_ for id_, vals in initial_values.items() if vals]
        if not ids:
            return
        fnames = self._track_get_fields()
        context = clean_context(self.env.context)
        ids_per_uid = defaultdict(list)
        for id_ in ids:
            ids_per_uid[writer_uids.get(id_, self.env.uid)].append(id_)
        overrides = {
            key: self.env.cr.precommit.data.pop(key)
            for key in (
                f"mail.tracking.message.{self._name}",
                f"mail.tracking.author.{self._name}",
            )
            if key in self.env.cr.precommit.data
        }
        for uid, uid_ids in ids_per_uid.items():
            self.env.cr.precommit.data.update(overrides)
            records = self.browse(uid_ids).with_user(uid).sudo()
            uid_context = context
            if uid != self.env.uid:
                uid_context = {k: v for k, v in context.items() if k != "lang"}
            tracking = records.with_context(uid_context)._message_track(
                fnames, initial_values
            )
            for record in records:
                changes, _tracking_value_ids = tracking.get(record.id, (None, None))
                record._message_track_post_template(changes)

    def _track_set_author(self, author: ResPartner) -> None:
        if not self._track_get_fields():
            return
        authors = self.env.cr.precommit.data.setdefault(
            f"mail.tracking.author.{self._name}", {}
        )
        for id_ in self.ids:
            authors[id_] = author

    def _track_post_template_finalize(self) -> None:
        self._message_track_post_template(
            self.env.cr.precommit.data.pop(
                f"mail.tracking.create.{self._name}.{self.id}", []
            )
        )

    def _track_set_log_message(self, message: str) -> None:
        if not self._track_get_fields():
            return
        body_values = self.env.cr.precommit.data.setdefault(
            f"mail.tracking.message.{self._name}", {}
        )
        for id_ in self.ids:
            body_values[id_] = message

    def _track_get_default_log_message(self, tracked_fields: Collection[str]) -> str:
        return ""

    @ormcache("self.env.uid", "self.env.su")
    def _track_get_fields(self) -> set[str]:
        model_fields = {
            name
            for name, field in self._fields.items()
            if getattr(field, "tracking", None)
        }
        model_fields |= {
            fname
            for fname, f in self._fields.items()
            if f.type == "properties"
            and f.definition_record in model_fields
            and getattr(f, "tracking", None) is not False
        }

        return model_fields and set(self.fields_get(model_fields, attributes=()))

    def _track_subtype(self, initial_values: dict) -> bool:
        self.ensure_one()
        return False

    def _message_track(
        self, fields_iter: Collection[str], initial_values_dict: dict
    ) -> dict:
        if not fields_iter:
            return {}

        tracked_fields = self.fields_get(
            fields_iter, attributes=("string", "type", "selection", "currency_field")
        )
        tracking = {}
        for record in self:
            try:
                tracking[record.id] = record._mail_track(
                    tracked_fields, initial_values_dict[record.id]
                )
            except MissingError:
                continue

        bodies = self.env.cr.precommit.data.pop(
            f"mail.tracking.message.{self._name}", {}
        )
        authors = self.env.cr.precommit.data.pop(
            f"mail.tracking.author.{self._name}", {}
        )
        for record in self:
            changes, tracking_value_ids = tracking.get(record.id, (None, None))
            if not changes:
                continue

            subtype = record._track_subtype(
                {
                    col_name: initial_values_dict[record.id][col_name]
                    for col_name in changes
                }
            )
            author_id = authors[record.id].id if record.id in authors else None
            body = (
                bodies[record.id]
                if record.id in bodies
                else record._track_get_default_log_message(changes)
            )
            if subtype and not subtype.exists():
                _logger.warning(
                    "mail.message.subtype %s no longer exists, logging %s "
                    "tracking without a subtype",
                    subtype.id,
                    self._name,
                )
                subtype = self.env["mail.message.subtype"]
            if subtype:
                record.message_post(
                    body=body,
                    author_id=author_id,
                    subtype_id=subtype.id,
                    tracking_value_ids=tracking_value_ids,
                )
            elif tracking_value_ids:
                record._message_log(
                    body=body,
                    author_id=author_id,
                    tracking_value_ids=tracking_value_ids,
                )

        return tracking

    def _message_track_post_template(
        self, changes: Collection[str] | None
    ) -> bool | None:
        if not self or not changes:
            return True
        cleaned_self = self.with_context(
            clean_context(self.env.context)
        )._fallback_lang()
        try:
            templates = self._track_template(changes)
        except MissingError:
            if not self.exists():
                return None
            raise

        default_composition_mode = "mass_mail" if len(self) != 1 else "comment"
        for template, post_kwargs in templates.values():
            if not template:
                continue

            composition_mode = post_kwargs.pop(
                "composition_mode", default_composition_mode
            )
            post_kwargs.setdefault("message_type", "auto_comment")
            post_kwargs.setdefault("notify_author_mention", True)
            if composition_mode == "mass_mail":
                cleaned_self.message_mail_with_source(template, **post_kwargs)
            else:
                cleaned_self.message_post_with_source(template, **post_kwargs)
        return True

    def _track_template(self, changes: Collection[str]) -> dict:
        return {}

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

        email_from = False
        if bounce_from := self.env.company.bounce_email:
            email_from = formataddr(("MAILER-DAEMON", bounce_from))
        if not email_from:
            catchall_aliases = self.env["mail.alias.domain"]._get_catchall_emails()
            if not any(
                catchall_email in (message["To"] or "")
                for catchall_email in catchall_aliases
            ):
                email_from = decode_message_header(message, "To")
        if not email_from:
            noreply = (
                self.env.company.default_from_email
                or self.env.company.catchall_email
                or self.env["mail.alias.domain"]
                ._get_default_domain()
                .default_from_email
            )
            email_from = formataddr(
                ("MAILER-DAEMON", noreply or self.env.user.email_normalized)
            )

        bounce_mail_values["email_from"] = email_from
        bounce_mail_values.update(mail_values)
        self.env["mail.mail"].sudo().create(bounce_mail_values).send()

    @api.model
    @ormcache()
    def _mail_get_blacklist_models(self) -> tuple[str, ...]:
        bl_models = (
            self.env["ir.model"]
            .sudo()
            .search(
                [
                    ("is_mail_blacklist", "=", True),
                    ("model", "!=", "mail.thread.blacklist"),
                ]
            )
        )
        return tuple(model.model for model in bl_models if model.model in self.env)

    @api.model
    def _routing_handle_bounce(
        self, email_message: EmailMessage, message_dict: dict
    ) -> None:
        bounced_record, bounced_record_done = False, False
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

            for model_name in self._mail_get_blacklist_models():
                rec_bounce_w_email = (
                    self.env[model_name]
                    .sudo()
                    .search([("email_normalized", "=", bounced_email)])
                )
                rec_bounce_w_email._message_receive_bounce(
                    bounced_email, bounced_partner
                )
                bounced_record_done = bounced_record_done or (
                    bounced_record
                    and model_name == bounced_model
                    and bounced_record in rec_bounce_w_email
                )

            if (
                bounced_record
                and not bounced_record_done
                and isinstance(bounced_record, self.pool["mail.thread"])
            ):
                bounced_record._message_receive_bounce(bounced_email, bounced_partner)

            if bounced_message and (bounced_email or bounced_partner):
                domain = Domain("mail_message_id", "=", bounced_message.id)
                sub_domains = []
                if bounced_partner:
                    sub_domains.append(
                        Domain("res_partner_id", "in", bounced_partner.ids)
                    )
                if bounced_email:
                    sub_domains.append(Domain("mail_email_address", "=", bounced_email))
                self.env["mail.notification"].sudo().search(
                    domain & Domain.OR(sub_domains)
                ).write(
                    {
                        "failure_reason": html2plaintext(
                            message_dict.get("body") or ""
                        ),
                        "failure_type": "mail_bounce",
                        "notification_status": "bounce",
                    }
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
    ) -> Route | tuple | Literal[False]:

        route = Route(*route)
        message_id = message_dict["message_id"]
        email_from = message_dict["email_from"]
        model, thread_id, alias = route.model, route.thread_id, route.alias
        record_set = None

        if not model:
            self._routing_warn(
                _("target model unspecified"), message_id, route, raise_exception
            )
            return ()
        if model not in self.env:
            self._routing_warn(
                _("unknown target model %s", model), message_id, route, raise_exception
            )
            return ()
        record_set = self.env[model].browse(thread_id) if thread_id else self.env[model]
        if record_set._abstract or record_set._transient:
            self._routing_warn(
                _("target model %s stores no document", model),
                message_id,
                route,
                raise_exception,
            )
            return ()

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
            return ()

        if alias:
            if not message_dict.get("author_id"):
                link_doc = record_set
                if (
                    not link_doc
                    and alias
                    and alias.alias_parent_model_id
                    and alias.alias_parent_thread_id
                ):
                    link_doc = self.env[alias.alias_parent_model_id.model].browse(
                        alias.alias_parent_thread_id
                    )
                link_doc = (
                    link_doc
                    if link_doc and self._mail_is_thread(link_doc)
                    else self.env["mail.thread"]
                )
                authors = link_doc._partner_find_from_emails_single(
                    [email_from], no_create=True
                )
                if authors:
                    message_dict["author_id"] = authors[0].id

            if thread_id:
                obj = record_set[0]
            elif alias.alias_parent_model_id and alias.alias_parent_thread_id:
                obj = self.env[alias.alias_parent_model_id.model].browse(
                    alias.alias_parent_thread_id
                )
            else:
                obj = self.env[model]
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
                alias._alias_bounce_incoming_email(
                    message, message_dict, set_invalid=error.is_config_error
                )
                return False

        return route._replace(model=model, thread_id=thread_id)

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
    ) -> list | None:
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
    def _detect_loop_sender(
        self, message: EmailMessage, message_dict: dict, routes: list[Route]
    ) -> bool:
        email_from = message_dict.get("email_from")
        if not email_from:
            return False

        email_from_normalized = email_normalize(email_from)

        if email_from_normalized and self.env[
            "mail.gateway.allowed"
        ].sudo().search_count([("email_normalized", "=", email_from_normalized)]):
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

            loop_new, loop_update = False, False
            search_new = any(not tid for tid in thread_ids)
            doc_ids = list(filter(None, thread_ids))

            if search_new:
                base_domain = model._detect_loop_sender_domain(email_from_normalized)
                if base_domain:
                    mail_new_count = model.sudo().search_count(
                        Domain.AND(
                            [
                                [("create_date", ">=", create_date_limit)],
                                base_domain,
                            ]
                        ),
                    )
                    loop_new = mail_new_count >= LOOP_THRESHOLD

            if doc_ids and not loop_new:
                base_msg_domain = Domain(
                    [
                        ("model", "=", model._name),
                        ("res_id", "in", doc_ids),
                        ("create_date", ">=", create_date_limit),
                        ("message_type", "=", "email"),
                    ]
                )
                if author_id:
                    msg_domain = Domain("author_id", "=", author_id) & base_msg_domain
                else:
                    msg_domain = (
                        Domain("email_from", "in", [email_from, email_from_normalized])
                        & base_msg_domain
                    )
                mail_update_groups = (
                    self.env["mail.message"]
                    .sudo()
                    ._read_group(msg_domain, ["res_id"], ["__count"])
                )
                if mail_update_groups:
                    loop_update = any(
                        group[1] >= LOOP_THRESHOLD for group in mail_update_groups
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
        claimed_localparts = {
            alias.alias_full_name.split("@", 1)[0]
            for alias in aliases
            if alias.alias_full_name in rcpt_tos_valid_list
        }
        return aliases.filtered(
            lambda alias: (
                alias.alias_full_name in rcpt_tos_valid_list
                or alias.alias_name not in claimed_localparts
            )
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

    def _route_bounce_catchall(self, message: EmailMessage, message_dict: dict) -> list:
        body = self.env["ir.qweb"]._render(
            "mail.mail_bounce_catchall",
            {
                "message": message_dict,
            },
        )
        self._routing_create_bounce_email(
            message_dict["email_from"],
            body,
            message,
            references=self._routing_bounce_references(message_dict),
            reply_to=self.env.company.email,
        )
        return []

    @api.model
    def message_route(
        self,
        message: EmailMessage,
        message_dict: dict,
        model: str | None = None,
        thread_id: int | None = None,
        custom_values: dict | None = None,
    ) -> list:
        if not isinstance(message, EmailMessage):
            raise TypeError(
                "message must be an email.message.EmailMessage at this point"
            )
        catchall_domains_allowed = list(
            filter(
                None,
                (
                    self.env["ir.config_parameter"]
                    .sudo()
                    .get_param("mail.catchall.domain.allowed")
                    or ""
                ).split(","),
            )
        )
        if catchall_domains_allowed:
            catchall_domains_allowed += self.env[
                "mail.alias.domain"
            ]._get_domain_names()

        def _filter_excluded_local_part(email: str) -> str | Literal[False]:
            left, _at, domain = email.partition("@")
            if not domain:
                return False
            if catchall_domains_allowed and domain not in catchall_domains_allowed:
                return False
            return left

        fallback_model = model

        if message_dict.get("is_bounce"):
            self._routing_handle_bounce(message, message_dict)
            return []
        self._routing_reset_bounce(message, message_dict)

        message_id = message_dict["message_id"]

        thread_references = message_dict["references"] or message_dict["in_reply_to"]
        msg_references = [
            r.strip()
            for r in unfold_references(thread_references)
            if "reply_to" not in r
        ]
        msg_references = msg_references[-32:]
        replying_to_msg = (
            self.env["mail.message"]
            .sudo()
            .search([("message_id", "in", msg_references)], limit=1, order="id desc")
            if msg_references
            else self.env["mail.message"]
        )
        is_a_reply, reply_model, reply_thread_id = (
            bool(replying_to_msg),
            replying_to_msg.model,
            replying_to_msg.res_id,
        )

        email_from = message_dict["email_from"]
        email_to_list = [e.lower() for e in email_split(message_dict["to"])]
        email_to_localparts = list(
            filter(
                None,
                (_filter_excluded_local_part(email_to) for email_to in email_to_list),
            )
        )
        rcpt_tos_list = [e.lower() for e in email_split(message_dict["recipients"])]
        rcpt_tos_localparts = list(
            filter(
                None,
                (_filter_excluded_local_part(email_to) for email_to in rcpt_tos_list),
            )
        )
        rcpt_tos_valid_list = list(rcpt_tos_list)

        if reply_model and reply_thread_id:
            reply_model_id = self.env["ir.model"]._get_id(reply_model)
            other_model_aliases = self.env["mail.alias"].search(
                [
                    "&",
                    ("alias_model_id", "!=", reply_model_id),
                    "|",
                    ("alias_full_name", "in", email_to_list),
                    "&",
                    ("alias_name", "in", email_to_localparts),
                    ("alias_incoming_local", "=", True),
                ]
            )
            if other_model_aliases:
                is_a_reply, reply_model, reply_thread_id = False, False, False
                rcpt_tos_valid_list = [
                    to
                    for to in rcpt_tos_valid_list
                    if (
                        to in other_model_aliases.mapped("alias_full_name")
                        or to.split("@", 1)[0]
                        in other_model_aliases.filtered("alias_incoming_local").mapped(
                            "alias_name"
                        )
                    )
                ]
        rcpt_tos_valid_localparts = list(
            filter(
                None,
                (
                    _filter_excluded_local_part(email_to)
                    for email_to in rcpt_tos_valid_list
                ),
            )
        )

        if is_a_reply and reply_model:
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
            )

            if not dest_aliases and reply_thread_id:
                target_record = (
                    self.env[reply_model].sudo().browse(reply_thread_id).exists()
                )
                if (
                    target_record
                    and "alias_id" in target_record._fields
                    and target_record.alias_id
                ):
                    dest_aliases = target_record.alias_id
                else:
                    model_aliases = self.env["mail.alias"].search(
                        [("alias_model_id", "=", reply_model_id)]
                    )
                    if model_aliases and all(
                        alias_.alias_contact != "everyone" for alias_ in model_aliases
                    ):
                        dest_aliases = model_aliases[:1]

            user_id = (
                self._mail_find_user_for_gateway(email_from, alias=dest_aliases).id
                or self.env.uid
            )
            route = self._routing_check_route(
                message,
                message_dict,
                Route(
                    reply_model, reply_thread_id, custom_values, user_id, dest_aliases
                ),
                raise_exception=False,
            )
            if route:
                _logger.info(
                    "Routing mail from %s to %s with Message-Id %s: direct reply to msg: model: %s, thread_id: %s, custom_values: %s, uid: %s",
                    email_from,
                    message_dict["to"],
                    message_id,
                    reply_model,
                    reply_thread_id,
                    custom_values,
                    self.env.uid,
                )
                return [route]
            if route is False:
                return []

        catchall_aliases = self.env["mail.alias.domain"]._get_catchall_emails()
        if rcpt_tos_list:
            message_dict.pop("parent_id", None)

            if self._detect_write_to_catchall(
                message_dict, catchall_aliases=catchall_aliases
            ):
                _logger.info(
                    "Routing mail from %s to %s with Message-Id %s: direct write to catchall, bounce",
                    email_from,
                    message_dict["to"],
                    message_id,
                )
                return self._route_bounce_catchall(message, message_dict)

            dest_aliases = self.env["mail.alias"].search(
                [
                    "|",
                    ("alias_full_name", "in", rcpt_tos_valid_list),
                    "&",
                    ("alias_name", "in", rcpt_tos_valid_localparts),
                    ("alias_incoming_local", "=", True),
                ]
            )
            dest_aliases = self._routing_filter_local_aliases(
                dest_aliases, rcpt_tos_valid_list
            )
            if dest_aliases:
                routes = []
                for alias in dest_aliases:
                    user_id = (
                        self._mail_find_user_for_gateway(email_from, alias=alias).id
                        or self.env.uid
                    )
                    route = Route(
                        alias.sudo().alias_model_id.model,
                        alias.alias_force_thread_id,
                        ast.literal_eval(alias.alias_defaults),
                        user_id,
                        alias,
                    )
                    AliasModel = (
                        self.env[route.model]
                        if route.model in self.env
                        and self._mail_is_thread(self.env[route.model])
                        else self
                    )
                    route = AliasModel._routing_check_route(
                        message, message_dict, route, raise_exception=True
                    )
                    if route:
                        _logger.info(
                            "Routing mail from %s to %s with Message-Id %s: direct alias match: %r",
                            email_from,
                            message_dict["to"],
                            message_id,
                            route,
                        )
                        routes.append(route)
                return routes

        if fallback_model:
            message_dict.pop("parent_id", None)
            user_id = self._mail_find_user_for_gateway(email_from).id or self.env.uid
            route = self._routing_check_route(
                message,
                message_dict,
                Route(fallback_model, thread_id, custom_values, user_id, None),
                raise_exception=True,
            )
            if route:
                _logger.info(
                    "Routing mail from %s to %s with Message-Id %s: fallback to model:%s, thread_id:%s, custom_values:%s, uid:%s",
                    email_from,
                    message_dict["to"],
                    message_id,
                    fallback_model,
                    thread_id,
                    custom_values,
                    user_id,
                )
                return [route]

        if rcpt_tos_list and self._detect_write_to_catchall(
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

    @api.model
    def _message_route_process(
        self, message: EmailMessage, message_dict: dict, routes: list[Route]
    ) -> int | Literal[False]:
        self = self.with_context(attachments_mime_plainxml=True)
        original_partner_ids = message_dict.pop("partner_ids", [])
        incoming_email_cc = message_dict.pop("cc_filtered", False)
        incoming_email_to = message_dict.pop("to_filtered", False)
        thread_id = False
        for model, thread_id, custom_values, user_id, alias in routes or ():
            subtype_id = False
            related_user = self.env["res.users"].browse(user_id)
            Model = self.env[model].with_context(
                mail_create_nosubscribe=True, mail_create_nolog=True
            )
            if not self._mail_is_thread(Model):
                raise ValueError(
                    "Undeliverable mail with Message-Id %s, model %s does not accept incoming emails"
                    % (message_dict["message_id"], model)
                )

            ModelCtx = Model.with_user(related_user).sudo()
            route_message_dict = message_dict
            if thread_id:
                thread = ModelCtx.browse(thread_id)
                thread.message_update(message_dict)
            else:
                route_message_dict = {
                    key: value
                    for key, value in message_dict.items()
                    if key != "parent_id"
                }
                try:
                    thread = ModelCtx.message_new(route_message_dict, custom_values)
                except Exception:
                    if alias:
                        with self.pool.cursor() as new_cr:
                            self.with_env(self.env(cr=new_cr)).env["mail.alias"].browse(
                                alias.id
                            )._alias_bounce_incoming_email(
                                message, message_dict, set_invalid=True
                            )
                    raise
                else:
                    if alias and alias.alias_status != "valid":
                        alias.alias_status = "valid"
                thread_id = thread.id
                subtype_id = thread._creation_subtype().id

            thread_root = thread.with_user(self.env.ref("base.user_root"))
            parent_message = False
            if route_message_dict.get("parent_id"):
                parent_message = (
                    self.env["mail.message"]
                    .sudo()
                    .browse(route_message_dict["parent_id"])
                )
            partner_ids = []
            if not subtype_id:
                if route_message_dict.get("is_internal"):
                    subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_note"
                    )
                else:
                    subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_comment"
                    )
            if parent_message and parent_message.author_id:
                if (
                    message_dict.get("is_internal")
                    or parent_message.author_id.partner_share
                ):
                    partner_ids = [parent_message.author_id.id]

            post_params = dict(
                incoming_email_cc=incoming_email_cc,
                incoming_email_to=incoming_email_to,
                subtype_id=subtype_id,
                partner_ids=partner_ids,
                **route_message_dict,
            )
            for x in (
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
            ):
                post_params.pop(x, None)
            new_msg = False
            if thread_root._name == "mail.thread":
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

    @api.model
    def message_new(self, msg_dict: dict, custom_values: dict | None = None) -> Self:
        data = {}
        if isinstance(custom_values, dict):
            data = custom_values.copy()
        name_field = self._rec_name or "name"
        if name_field in self._fields and not data.get(name_field):
            data[name_field] = msg_dict.get("subject", "")

        primary_email = self._mail_get_primary_email_field()
        if primary_email and msg_dict.get("email_from"):
            data[primary_email] = msg_dict["email_from"]

        return self.create(data)

    def message_update(
        self, msg_dict: dict, update_vals: ValuesType | None = None
    ) -> bool:
        if update_vals:
            self.write(update_vals)
        return True

    def _message_receive_bounce(self, email: str, partner: ResPartner) -> None:
        pass

    def _message_reset_bounce(self, email: str) -> None:
        pass

    def _message_parse_extract_payload_postprocess(
        self, message: EmailMessage, payload_dict: dict
    ) -> dict:
        body, attachments = payload_dict["body"], payload_dict["attachments"]
        if not body.strip():
            return {"body": body, "attachments": attachments}
        try:
            root = lxml.html.fromstring(body)
        except ValueError:
            root = lxml.html.fromstring(body.encode("utf-8"))

        postprocessed = False
        to_remove = []
        for node in root.iter():
            if "o_mail_notification" in (
                node.get("class") or ""
            ) or "o_mail_notification" in (node.get("summary") or ""):
                postprocessed = True
                if node.getparent() is not None:
                    to_remove.append(node)
            if node.tag == "img" and node.get("src", "").startswith("cid:"):
                cid = node.get("src").split(":", 1)[1]
                related_attachment = [
                    attach
                    for attach in attachments
                    if attach[2] and attach[2].get("cid") == cid
                ]
                if related_attachment:
                    node.set("data-filename", related_attachment[0][0])
                    postprocessed = True

        for node in to_remove:
            node.getparent().remove(node)
        if postprocessed:
            body = Markup(etree.tostring(root, pretty_print=False, encoding="unicode"))
        return {"body": body, "attachments": attachments}

    def _message_parse_extract_payload(
        self, message: EmailMessage, message_dict: dict, save_original: bool = False
    ) -> dict:
        attachments = []
        body = ""
        if save_original:
            attachments.append(
                self._Attachment("original_email.eml", message.as_string(), {})
            )

        if message.get_content_maintype() == "text":
            body = _email_part_get_content_safe(message)
            if message.get_content_type() == "text/plain":
                body = append_content_to_html("", body, preserve=True)
            elif message.get_content_type() == "text/html":
                body = html_sanitize(body, sanitize_tags=False, strip_classes=True)
        else:
            alternative = False
            mixed = False
            has_html = False
            sanitize_body = False
            for part in message.walk():
                if message_dict.get("is_bounce") and body:
                    break
                if (bad_content_type := part.get_content_type()) in BAD_CONTENT_TYPES:
                    _logger.warning(
                        "Message containing an unexpected Content-Type %r, assuming 'application/octet-stream'",
                        bad_content_type,
                    )
                    part.replace_header("Content-Type", "application/octet-stream")
                if part.get_content_type() == "multipart/alternative":
                    alternative = True
                if part.get_content_type() == "multipart/mixed":
                    mixed = True
                if part.get_content_maintype() == "multipart":
                    continue

                filename = part.get_filename()
                if part.get_content_type().startswith("text/") and not part.get_param(
                    "charset"
                ):
                    part.set_charset("utf-8")
                encoding = part.get_content_charset()

                if part.get("Content-Type", "").startswith("pdf;"):
                    part.replace_header(
                        "Content-Type",
                        "application/pdf" + part.get("Content-Type", "")[3:],
                    )

                content = _email_part_get_content_safe(part)
                info = {"encoding": encoding}
                if filename and part.get("content-id"):
                    info["cid"] = part.get("content-id").strip("><")
                    attachments.append(self._Attachment(filename, content, info))
                    continue
                if filename or part.get("content-disposition", "").strip().startswith(
                    "attachment"
                ):
                    attachments.append(
                        self._Attachment(filename or "attachment", content, info)
                    )
                    continue
                if part.get_content_type() == "text/plain" and not (
                    alternative and body
                ):
                    body = append_content_to_html(body, content, preserve=True)
                elif part.get_content_type() == "text/html":
                    if alternative and not (has_html and mixed):
                        body = content
                    else:
                        body = append_content_to_html(body, content, plaintext=False)
                    has_html = has_html or bool(content)
                    sanitize_body = True
                else:
                    attachments.append(
                        self._Attachment(filename or "attachment", content, info)
                    )

            if sanitize_body:
                body = html_sanitize(body, sanitize_tags=False, strip_classes=True)

        return self._message_parse_extract_payload_postprocess(
            message, {"body": body, "attachments": attachments}
        )

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

        email_part = next(
            (
                part
                for part in email_message.walk()
                if part.get_content_type() in {"message/rfc822", "text/rfc822-headers"}
            ),
            None,
        )
        if not email_part:
            email_part = next(
                (
                    part
                    for part in email_message.walk()
                    if part.get_content_type() == "multipart/report"
                ),
                None,
            )

        dsn_part = next(
            (
                part
                for part in email_message.walk()
                if part.get_content_type() == "message/delivery-status"
            ),
            None,
        )

        bounced_email = False
        bounced_partner = self.env["res.partner"].sudo()
        dsn_payload = dsn_part.get_payload() if dsn_part else None
        if isinstance(dsn_payload, list) and len(dsn_payload) > 1:
            dsn = dsn_payload[1]
            final_recipient_data = decode_message_header(dsn, "Final-Recipient")
            if final_recipient_data and ";" in final_recipient_data:
                bounced_email = email_normalize(
                    final_recipient_data.split(";", 1)[1].strip()
                )
            if bounced_email:
                bounced_partner = (
                    self.env["res.partner"]
                    .sudo()
                    .search([("email_normalized", "=", bounced_email)])
                )

        bounced_msg_ids = False
        bounced_message = self.env["mail.message"].sudo()
        if email_part:
            if email_part.get_content_type() == "text/rfc822-headers":
                email_payload = message_from_string(
                    _email_part_get_content_safe(email_part), policy=email.policy.SMTP
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
            raise ValueError(_("Message should be a valid EmailMessage instance"))
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
            link_doc = (
                self.env[model].browse(thread_id) if thread_id else self.env[model]
            )
            if (
                not link_doc
                and alias
                and alias.alias_parent_model_id
                and alias.alias_parent_thread_id
            ):
                link_doc = self.env[alias.alias_parent_model_id.model].browse(
                    alias.alias_parent_thread_id
                )
            link_doc = (
                link_doc
                if link_doc and self._mail_is_thread(link_doc)
                else self.env["mail.thread"]
            )

            if not values.get("author_id") and message_dict["email_from"]:
                author = link_doc._partner_find_from_emails_single(
                    [message_dict["email_from"]], no_create=True
                )
                if author:
                    values["author_id"] = author.id
            if not values.get("partner_ids") and message_dict["recipients"]:
                values["partner_ids"] = link_doc._partner_find_from_emails_single(
                    email_split(message_dict["recipients"]), no_create=True
                ).ids
        return values

    def _get_bounced_message_data(
        self, message: EmailMessage, message_dict: dict
    ) -> tuple:
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
        in_reply_to = msg_dict["in_reply_to"]
        if in_reply_to:
            parent = (
                self.env["mail.message"]
                .sudo()
                .search([("message_id", "=", in_reply_to)], order="id DESC", limit=1)
            )
            if parent:
                return parent

        msg_references = [r.strip() for r in unfold_references(msg_dict["references"])]
        if msg_references:
            msg_references = msg_references[-32:]
            parent = (
                self.env["mail.message"]
                .sudo()
                .search(
                    [("message_id", "in", msg_references)], order="id DESC", limit=1
                )
            )
            if parent:
                return parent

        return None

    def _partner_find_from_emails_single(
        self,
        emails: list[str],
        avoid_alias: bool = True,
        ban_emails: list[str] | None = None,
        filter_found: Callable[[ResPartner], Any] | None = None,
        additional_values: dict | None = None,
        no_create: bool = False,
    ) -> ResPartner:
        if self:
            self.ensure_one()
        return self._partner_find_from_emails(
            {self: emails},
            avoid_alias=avoid_alias,
            ban_emails=ban_emails,
            filter_found=filter_found,
            additional_values=additional_values,
            no_create=no_create,
        )[self.id]

    def _partner_find_from_emails(
        self,
        records_emails: dict[models.BaseModel, list[str]],
        avoid_alias: bool = True,
        ban_emails: list[str] | None = None,
        filter_found: Callable[[ResPartner], Any] | None = None,
        additional_values: dict | None = None,
        no_create: bool = False,
    ) -> dict:
        if self and len(self) != len(records_emails):
            raise ValueError(
                "Invoke with either self maching records_emails, either on a void recordset."
            )
        res_ids = self.ids or [record.id for record in records_emails]
        found_results = dict.fromkeys(res_ids, self.env["res.partner"])
        emails_all = []
        emails_key_all = []
        emails_key_company_id = {}
        emails_key_res_ids = defaultdict(list)

        records_company = self.sudo()._mail_get_companies()
        emails_normalized_info = self._get_customer_information()
        for email_key, update in (additional_values or {}).items():
            emails_normalized_info.setdefault(email_key, {}).update(**update)

        for record, mails in records_emails.items():
            record_company = records_company.get(record.id, self.env["res.company"])
            for mail in mails:
                mail_normalized = email_normalize(mail, strict=False)
                email_key = mail_normalized or mail
                emails_key_res_ids[email_key].append(record.id)
                if record_company and email_key:
                    known_company_id = emails_key_company_id.get(
                        email_key, record_company.id
                    )
                    emails_key_company_id[email_key] = (
                        record_company.id
                        if known_company_id == record_company.id
                        else False
                    )
                emails_all.append(mail)
                emails_key_all.append(email_key)
        if not emails_all:
            return found_results

        followers = (
            self.sudo().message_partner_ids
            if "message_partner_ids" in self
            else self.env["res.partner"]
        )
        alias_emails = (
            self.env["mail.alias.domain"].sudo()._find_aliases(emails_key_all)
            if avoid_alias
            else []
        )
        ban_emails = (ban_emails or []) + alias_emails

        follower_ids = set(followers._ids)
        current_partner_id = self.env.user.partner_id.id

        def sort_key(p: ResPartner) -> tuple:
            return (
                p.id == current_partner_id,
                p.id in follower_ids,
                not p.partner_share,
                bool(p.user_ids),
                p.company_id.id == emails_key_company_id.get(p.email_normalized, False),
                not p.company_id,
            )

        partners = self.env["res.partner"]._find_or_create_from_emails(
            emails_all,
            additional_values={
                mail_key: {
                    "company_id": emails_key_company_id.get(mail_key, False),
                    **emails_normalized_info.get(mail_key, {}),
                }
                for mail_key in emails_key_all
            },
            ban_emails=ban_emails,
            filter_found=filter_found,
            no_create=no_create,
            sort_key=sort_key,
            sort_reverse=True,
        )

        for mail, partner in zip(emails_all, partners, strict=False):
            mail_key = email_normalize(mail, strict=False) or mail
            for res_id in emails_key_res_ids[mail_key]:
                found_results[res_id] |= partner
        return found_results

    def _mail_find_user_for_gateway(
        self, email_value: str, alias: MailAlias | None = None
    ) -> ResUsers:
        normalized_email = email_normalize(email_value)
        if not normalized_email:
            return self.env["res.users"]

        record_su = self.env["mail.thread"].sudo()
        if alias and alias.alias_parent_model_id and alias.alias_parent_thread_id:
            record_su = (
                self.env[alias.alias_parent_model_id.sudo().model]
                .browse(alias.alias_parent_thread_id)
                .sudo()
            )
            record_su = (
                record_su
                if self._mail_is_thread(record_su)
                else self.env["mail.thread"].sudo()
            )

        partner = record_su._partner_find_from_emails_single(
            [email_value], filter_found=lambda p: p.user_ids, no_create=True
        )
        return partner.main_user_id

    @api.model
    def _mail_find_partner_from_emails(
        self,
        emails: list[str],
        records: models.BaseModel | None = None,
        force_create: bool = False,
        extra_domain: Domain | list | Literal[False] = False,
    ) -> list:
        if records and self._mail_is_thread(records):
            per_record = records._partner_find_from_emails(
                dict.fromkeys(records, emails),
                avoid_alias=True,
                no_create=not force_create,
            )
            all_partners = self.env["res.partner"].browse(
                {
                    partner.id
                    for partners in per_record.values()
                    for partner in partners
                    if partner.id
                }
            )
        else:
            all_partners = self.env["mail.thread"]._partner_find_from_emails_single(
                emails,
                avoid_alias=True,
                no_create=not force_create,
            )
        void = self.env["res.partner"]
        partner_by_email = {}
        for partner in all_partners:
            for email_key in (partner.email_normalized, partner.email):
                if email_key:
                    partner_by_email.setdefault(email_key, partner)
        return [
            partner_by_email.get(
                email_normalize(email_input) or email_input or None, void
            )
            for email_input in emails
        ]

    def _get_customer_information(self) -> dict:
        return {}

    def message_post(
        self,
        *,
        body: str = "",
        subject: str | None = None,
        message_type: str = "notification",
        email_from: str | None = None,
        author_id: int | None = None,
        parent_id: int | Literal[False] = False,
        subtype_xmlid: str | None = None,
        subtype_id: int | Literal[False] = False,
        partner_ids: list[int] | None = None,
        outgoing_email_to: str | Literal[False] = False,
        incoming_email_to: str | Literal[False] = False,
        incoming_email_cc: str | Literal[False] = False,
        attachments: list[tuple | list] | None = None,
        attachment_ids: list[int] | None = None,
        body_is_html: bool = False,
        **kwargs,
    ) -> MailMessage:
        self.ensure_one()

        self._raise_for_invalid_parameters(
            set(kwargs.keys()), forbidden_names={"model", "res_id", "subtype"}
        )
        if self._name == "mail.thread" or not self.id:
            raise ValueError(
                _(
                    "Posting a message should be done on a business document. Use message_notify to send a notification to an user."
                )
            )
        if message_type == "user_notification":
            raise ValueError(_("Use message_notify to send a notification to an user."))
        if attachments:
            format_error = not is_list_of(attachments, list) and not is_list_of(
                attachments, tuple
            )
            if not format_error:
                format_error = not all(
                    len(attachment) in {2, 3} for attachment in attachments
                )
            if format_error:
                raise ValueError(
                    _(
                        "Posting a message should receive attachments as a list of list or tuples (received %(aids)s)",
                        aids=repr(attachments),
                    )
                )
        if attachment_ids and not is_list_of(attachment_ids, int):
            raise ValueError(
                _(
                    "Posting a message should receive attachments records as a list of IDs (received %(aids)s)",
                    aids=repr(attachment_ids),
                )
            )
        attachment_ids = list(attachment_ids or [])
        if partner_ids and not is_list_of(partner_ids, int):
            raise ValueError(
                _(
                    "Posting a message should receive partners as a list of IDs (received %(pids)s)",
                    pids=repr(partner_ids),
                )
            )
        partner_ids = list(partner_ids or [])

        msg_kwargs = {
            key: val
            for key, val in kwargs.items()
            if key in self.env["mail.message"]._fields
        }
        notif_kwargs = {
            key: val for key, val in kwargs.items() if key not in msg_kwargs
        }

        self = self._fallback_lang()

        guest = self.env["mail.guest"]._get_guest_from_context()
        if not author_id and self.env.user._is_public() and guest:
            author_guest_id = guest.id
            author_id, email_from = False, False
        else:
            author_guest_id = False
            author_id, email_from = self._message_compute_author(author_id, email_from)

        if subtype_xmlid:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(subtype_xmlid)
        if not subtype_id:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note")

        if self.env.context.get("mail_post_autofollow") and partner_ids:
            self.message_subscribe(partner_ids=list(partner_ids))
        elif (
            partner_ids
            and self.env.context.get("mail_post_autofollow") is not False
            and self._mail_thread_customer
        ):
            customer = self._mail_get_customer()
            if customer.id in partner_ids:
                self.message_subscribe(partner_ids=customer.ids)

        msg_values = dict(msg_kwargs)
        if "email_add_signature" not in msg_values:
            msg_values["email_add_signature"] = True
        if body_is_html and self.env.user._is_internal():
            _logger.warning(
                "Posting HTML message using body_is_html=True, use a Markup object instead (user: %s)",
                self.env.user.id,
            )
            body = Markup(body)
        msg_values.update(
            {
                "author_id": author_id,
                "author_guest_id": author_guest_id,
                "email_from": email_from,
                "model": self._name,
                "res_id": self.id,
                "body": _escape_body(body),
                "message_type": message_type,
                "parent_id": self._message_compute_parent_id(parent_id),
                "subject": subject or False,
                "subtype_id": subtype_id,
                "partner_ids": partner_ids,
                "incoming_email_to": incoming_email_to,
                "incoming_email_cc": incoming_email_cc,
                "outgoing_email_to": outgoing_email_to,
            }
        )
        if "record_alias_domain_id" not in msg_values:
            msg_values["record_alias_domain_id"] = (
                self.sudo()
                ._mail_get_alias_domains(default_company=self.env.company)[self.id]
                .id
            )
        if "record_company_id" not in msg_values:
            msg_values["record_company_id"] = self._mail_get_companies(
                default=self.env.company
            )[self.id].id
        if "reply_to" not in msg_values:
            msg_values["reply_to"] = self._notify_get_reply_to(
                default=email_from, author_id=author_id
            )[self.id]

        msg_values.update(
            self._process_attachments_for_post(attachments, attachment_ids, msg_values)
        )
        new_message = self._message_create([msg_values])

        author_subscribe = (
            not self.env.context.get("mail_post_autofollow_author_skip")
            and msg_values["message_type"]
            not in (
                "notification",
                "user_notification",
                "auto_comment",
                "out_of_office",
            )
            and subtype_id
            == self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_comment")
        )
        if author_subscribe:
            real_author = self._message_compute_real_author(msg_values["author_id"])
            if real_author and not real_author.partner_share:
                self._message_subscribe(partner_ids=[real_author.id])

        self._message_post_after_hook(new_message, msg_values)
        self._notify_thread(new_message, msg_values, **notif_kwargs)
        return new_message

    def _message_post_after_hook(self, message: MailMessage, msg_values: dict) -> None:
        return

    def _message_mail_after_hook(self, mails: MailMail) -> None:
        return

    def _process_attachments_for_post(
        self,
        attachments: list[tuple | list] | None,
        attachment_ids: list[int],
        message_values: dict,
    ) -> dict:
        if "res_id" in message_values:
            model, res_id = message_values["model"], message_values["res_id"]
        else:
            self.ensure_one()
            model, res_id = self._name, self.id
        body = ""
        if message_values.get("body"):
            body = (
                escape(message_values["body"])
                if not is_html_empty(message_values["body"])
                else ""
            )

        m2m_attachment_ids = []
        if attachment_ids:
            filtered_attachment_ids = (
                self.env["ir.attachment"]
                .sudo()
                .browse(attachment_ids)
                .filtered(
                    lambda a: (
                        a.res_model
                        in ("mail.compose.message", "mail.scheduled.message")
                        and a.create_uid.id == self.env.uid
                    )
                )
            )
            if filtered_attachment_ids:
                filtered_attachment_ids.write({"res_model": model, "res_id": res_id})
            if not self.env.user._is_internal():
                attachment_ids = filtered_attachment_ids.ids

            m2m_attachment_ids += [(4, att_id) for att_id in attachment_ids]

        return_values = {}
        if attachments:
            body_cids, body_filenames = set(), set()
            if body:
                root = lxml.html.fromstring(body)
                for node in root.iter("img"):
                    if node.get("src", "").startswith("cid:"):
                        body_cids.add(node.get("src").split("cid:")[1])
                    elif node.get("data-filename"):
                        body_filenames.add(node.get("data-filename"))

            attachement_values_list = []
            attachement_extra_list = []
            for attachment in attachments:
                if len(attachment) == 2:
                    name, content = attachment
                    cid = False
                    info = {}
                elif len(attachment) == 3:
                    name, content, info = attachment
                    cid = info and info.get("cid")
                else:
                    continue

                if isinstance(content, str):
                    encoding = info and info.get("encoding")
                    try:
                        content = content.encode(encoding or "utf-8")
                    except UnicodeEncodeError:
                        content = content.encode("utf-8")
                elif isinstance(content, EmailMessage):
                    content = content.as_bytes()
                elif content is None:
                    continue
                attachement_values = {
                    "name": name,
                    "datas": base64.b64encode(content),
                    "type": "binary",
                    "description": name,
                    "res_model": model,
                    "res_id": res_id,
                }
                token = False
                if (cid and cid in body_cids) or (name and name in body_filenames):
                    token = self.env["ir.attachment"]._generate_access_token()
                    attachement_values["access_token"] = token
                attachement_values_list.append(attachement_values)

                attachement_extra_list.append((cid, name, token, info))

            new_attachments = self._create_attachments_for_post(
                attachement_values_list, attachement_extra_list
            )
            attach_cid_mapping, attach_name_mapping = {}, {}
            for attachment, (cid, name, token, _info) in zip(
                new_attachments, attachement_extra_list, strict=False
            ):
                if cid:
                    attach_cid_mapping[cid] = (attachment.id, token)
                if name:
                    attach_name_mapping[name] = (attachment.id, token)
                m2m_attachment_ids.append((4, attachment.id))

            if (body_cids or body_filenames) and body:
                postprocessed = False
                for node in root.iter("img"):
                    att_id, token = False, False
                    if node.get("src", "").startswith("cid:"):
                        cid = node.get("src").split("cid:")[1]
                        att_id, token = attach_cid_mapping.get(cid, (False, False))
                    if (not att_id or not token) and node.get("data-filename"):
                        att_id, token = attach_name_mapping.get(
                            node.get("data-filename"), (False, False)
                        )
                    if att_id and token:
                        node.set("src", f"/web/image/{att_id}?access_token={token}")
                        postprocessed = True
                if postprocessed:
                    return_values["body"] = Markup(
                        lxml.html.tostring(root, pretty_print=False, encoding="unicode")
                    )
        return_values["attachment_ids"] = m2m_attachment_ids
        return return_values

    def _create_attachments_for_post(
        self, values_list: list[dict], extra_list: list[tuple]
    ) -> IrAttachment:
        return self.env["ir.attachment"].sudo().create(values_list)

    def _process_attachments_for_template_post(
        self, mail_template: MailTemplate
    ) -> dict:
        return {}

    def message_mail_with_source(
        self,
        source_ref: models.BaseModel | str,
        *,
        render_values: dict | None = None,
        message_type: str = "notification",
        auto_commit: bool = False,
        **kwargs,
    ) -> MailMail:
        template, view = self._get_source_from_ref(source_ref)

        self._raise_for_invalid_parameters(
            set(kwargs.keys()),
            forbidden_names={
                "body",
                "composition_mode",
                "incoming_email_cc",
                "incoming_email_to",
                "model",
                "res_id",
                "outgoing_email_to",
                "values",
            },
        )

        bodies = (
            self.env["mail.render.mixin"]._render_template_qweb_view(
                view,
                self._name,
                self.ids,
                add_context=render_values,
            )
            if view
            else {}
        )

        composer_values = {
            "composition_mode": "mass_mail",
            "message_type": message_type,
            "subtype_id": kwargs.pop("subtype_id", False)
            or self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note"),
            **kwargs,
        }
        composer_ctx = {
            "default_composition_mode": "mass_mail",
            "default_model": self._name,
            "default_template_id": template.id if template else False,
        }

        mails_su = self.env["mail.mail"].sudo()
        for subset in [self] if template else self:
            composer_ctx["default_res_ids"] = subset.ids
            if not template:
                composer_values["body"] = bodies[subset.id]

            composer = (
                self.env["mail.compose.message"]
                .with_context(**composer_ctx)
                .create(composer_values)
            )
            mails_as_sudo, _messages = composer._action_send_mail(
                auto_commit=auto_commit
            )
            mails_su += mails_as_sudo
        return mails_su

    def message_post_with_source(
        self,
        source_ref: models.BaseModel | str,
        *,
        render_values: dict | None = None,
        message_type: str = "notification",
        subtype_xmlid: str | Literal[False] = False,
        subtype_id: int | Literal[False] = False,
        **kwargs,
    ) -> MailMessage:
        template, view = self._get_source_from_ref(source_ref)

        self._raise_for_invalid_parameters(
            set(kwargs.keys()),
            forbidden_names={
                "body",
                "composition_mode",
                "incoming_email_cc",
                "incoming_email_to",
                "model",
                "res_id",
                "outgoing_email_to",
                "values",
            },
        )

        bodies = (
            self.env["mail.render.mixin"]._render_template_qweb_view(
                view,
                self._name,
                self.ids,
                add_context=render_values,
            )
            if view
            else {}
        )

        if subtype_xmlid:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(subtype_xmlid)
        if not subtype_id:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note")

        messages_all = self.env["mail.message"]
        for record in self:
            if template:
                composer = (
                    self.env["mail.compose.message"]
                    .with_context(
                        default_composition_mode="comment",
                        default_model=self._name,
                        default_res_ids=record.ids,
                        default_template_id=template.id,
                    )
                    .create(
                        {
                            "message_type": message_type,
                            "subtype_id": subtype_id,
                            **kwargs,
                        }
                    )
                )
                _mails_as_sudo, messages = composer._action_send_mail()
                messages_all += messages
            else:
                messages_all += record.message_post(
                    body=bodies[record.id],
                    message_type=message_type,
                    subtype_id=subtype_id,
                    **kwargs,
                )
        return messages_all

    def message_notify(
        self,
        *,
        body: str = "",
        subject: str | Literal[False] = False,
        author_id: int | None = None,
        email_from: str | None = None,
        model: str | Literal[False] = False,
        res_id: int | Literal[False] = False,
        subtype_xmlid: str | None = None,
        subtype_id: int | Literal[False] = False,
        partner_ids: list[int] | Literal[False] = False,
        attachments: list[tuple | list] | None = None,
        attachment_ids: list[int] | None = None,
        **kwargs,
    ) -> MailMessage:
        if self:
            self.ensure_one()
        key = self.id if self else False
        return self._message_notify_batch(
            {key: body},
            subjects={key: subject},
            author_id=author_id,
            email_from=email_from,
            model=model,
            res_id=res_id,
            subtype_xmlid=subtype_xmlid,
            subtype_id=subtype_id,
            partner_ids=partner_ids,
            attachments=attachments,
            attachment_ids=attachment_ids,
            **kwargs,
        )

    def _message_notify_batch(
        self,
        bodies: dict,
        *,
        subjects: dict | None = None,
        author_id: int | None = None,
        email_from: str | None = None,
        model: str | Literal[False] = False,
        res_id: int | Literal[False] = False,
        subtype_xmlid: str | None = None,
        subtype_id: int | Literal[False] = False,
        partner_ids: list[int] | Literal[False] = False,
        attachments: list[tuple | list] | None = None,
        attachment_ids: list[int] | None = None,
        **kwargs,
    ) -> MailMessage:
        if not partner_ids:
            _logger.warning("Message notify called without recipient_ids, skipping")
            return self.env["mail.message"]
        if len(bodies) > 1 and (attachments or attachment_ids):
            raise ValueError(
                _(
                    "Batch notification cannot support attachments on more than 1 document"
                )
            )

        self._raise_for_invalid_parameters(
            set(kwargs.keys()),
            forbidden_names={
                "incoming_email_cc",
                "incoming_email_to",
                "message_id",
                "message_type",
                "outgoing_email_to",
                "parent_id",
            },
        )
        if attachments:
            valid = all(
                isinstance(attachment, (list, tuple)) and len(attachment) in (3, 2)
                for attachment in attachments
            )
            if not valid:
                raise ValueError(
                    _(
                        "Notification should receive attachments as a list of list or tuples (received %(aids)s)",
                        aids=repr(attachments),
                    )
                )
        if attachment_ids and not is_list_of(attachment_ids, int):
            raise ValueError(
                _(
                    "Notification should receive attachments records as a list of IDs (received %(aids)s)",
                    aids=repr(attachment_ids),
                )
            )
        if not is_list_of(partner_ids, int):
            raise ValueError(
                _(
                    "Notification should receive partners given as a list of IDs (received %(pids)s)",
                    pids=repr(partner_ids),
                )
            )

        msg_kwargs = {
            key: val
            for key, val in kwargs.items()
            if key in self.env["mail.message"]._fields
        }
        notif_kwargs = {
            key: val for key, val in kwargs.items() if key not in msg_kwargs
        }
        if len(bodies) > 1 and (
            flattened := {"record_alias_domain_id", "record_company_id", "reply_to"}
            & set(msg_kwargs)
        ):
            raise ValueError(
                _(
                    "Batch notification derives %(param_names)s from each document and cannot take them per call",
                    param_names=", ".join(sorted(flattened)),
                )
            )
        notif_kwargs["notify_author_mention"] = notif_kwargs.get(
            "notify_author_mention", True
        )

        author_source = self if len(self) == 1 else self.browse()
        author_id, email_from = author_source._message_compute_author(
            author_id, email_from
        )

        if not model or not res_id:
            model, res_id = False, False

        if subtype_xmlid:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(subtype_xmlid)
        if not subtype_id:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note")

        subjects = subjects or {}
        alias_domains = (
            self._mail_get_alias_domains(default_company=self.env.company)
            if self and "record_alias_domain_id" not in msg_kwargs
            else {}
        )
        companies = (
            self._mail_get_companies(default=self.env.company)
            if self and "record_company_id" not in msg_kwargs
            else {}
        )
        reply_tos = (
            self._notify_get_reply_to(default=email_from, author_id=author_id)
            if "reply_to" not in msg_kwargs
            else {}
        )

        values_list = []
        notified_records = []
        for record_id, body in bodies.items():
            notified_records.append(
                self.browse(record_id) if record_id else self.browse()
            )
            msg_values = {
                "author_id": author_id,
                "email_from": email_from,
                "model": self._name if record_id else model,
                "res_id": record_id or res_id,
                "body": _escape_body(body),
                "is_internal": True,
                "message_type": "user_notification",
                "subject": subjects.get(record_id, False),
                "subtype_id": subtype_id,
                "message_id": generate_tracking_message_id("message-notify"),
                "partner_ids": partner_ids,
                "email_add_signature": True,
            }
            msg_values.update(msg_kwargs)
            if record_id:
                if "record_alias_domain_id" not in msg_values:
                    msg_values["record_alias_domain_id"] = alias_domains[record_id].id
                if "record_company_id" not in msg_values:
                    msg_values["record_company_id"] = companies[record_id].id
            if "reply_to" not in msg_values:
                msg_values["reply_to"] = reply_tos[record_id]
            if attachments or attachment_ids:
                msg_values.update(
                    self._process_attachments_for_post(
                        attachments, attachment_ids, msg_values
                    )
                )
            values_list.append(msg_values)

        messages = self._message_create(values_list)
        for message, msg_values, notified in zip(
            messages, values_list, notified_records, strict=True
        ):
            notified._fallback_lang()._notify_thread(
                message, msg_values, **notif_kwargs
            )
        return messages

    def _message_log_with_view(
        self,
        view_ref: models.BaseModel | str | int,
        render_values: dict | None = None,
        message_type: str = "notification",
        **kwargs,
    ) -> MailMessage:
        self._raise_for_invalid_parameters(
            set(kwargs.keys()),
            forbidden_names={
                "body",
                "bodies",
                "incoming_email_cc",
                "incoming_email_to",
                "outgoing_email_to",
            },
        )

        bodies = self.env["mail.render.mixin"]._render_template_qweb_view(
            view_ref,
            self._name,
            self.ids,
            add_context=render_values,
        )

        return self._message_log_batch(
            bodies=bodies, message_type=message_type, **kwargs
        )

    def _message_log(
        self,
        *,
        body: str = "",
        subject: str | Literal[False] = False,
        author_id: int | None = None,
        email_from: str | None = None,
        message_type: str = "notification",
        partner_ids: list[int] | Literal[False] = False,
        attachment_ids: list[int] | Literal[False] = False,
        tracking_value_ids: list | Literal[False] = False,
    ) -> MailMessage:
        self.ensure_one()

        return self._message_log_batch(
            {self.id: body},
            subject=subject,
            author_id=author_id,
            email_from=email_from,
            message_type=message_type,
            partner_ids=partner_ids,
            attachment_ids=attachment_ids,
            tracking_value_ids=tracking_value_ids,
        )

    def _message_log_batch(
        self,
        bodies: dict,
        subject: str | Literal[False] = False,
        author_id: int | None = None,
        email_from: str | None = None,
        message_type: str = "notification",
        partner_ids: list[int] | Literal[False] = False,
        attachment_ids: list[int] | Literal[False] = False,
        tracking_value_ids: list | Literal[False] = False,
    ) -> MailMessage:
        if len(self) > 1 and (attachment_ids or tracking_value_ids):
            raise ValueError(
                _(
                    "Batch log cannot support attachments or tracking values on more than 1 document"
                )
            )

        author_source = self if len(self) == 1 else self.browse()
        author_id, email_from = author_source._message_compute_author(
            author_id, email_from
        )

        base_message_values = {
            "author_id": author_id,
            "email_from": email_from,
            "model": self._name,
            "record_alias_domain_id": False,
            "record_company_id": False,
            "attachment_ids": attachment_ids,
            "message_type": message_type,
            "is_internal": True,
            "subject": subject,
            "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note"),
            "tracking_value_ids": tracking_value_ids,
            "email_add_signature": False,
            "partner_ids": partner_ids,
            "reply_to": self.env["mail.thread"]._notify_get_reply_to(
                default=email_from, author_id=author_id
            )[False],
        }

        values_list = [
            dict(
                base_message_values,
                res_id=record.id,
                body=_escape_body(bodies.get(record.id)),
                message_id=generate_tracking_message_id("message-notify"),
            )
            for record in self
        ]
        return self.sudo()._message_create(values_list)

    def _message_compute_author(
        self, author_id: int | None = None, email_from: str | None = None
    ) -> tuple:
        if author_id is None:
            if email_from:
                author = self._partner_find_from_emails_single(
                    [email_from], no_create=True
                )
            else:
                author = self.env.user.partner_id
                email_from = author.email_formatted
            author_id = author.id

        if email_from is None:
            if author_id:
                author = self.env["res.partner"].browse(author_id)
                email_from = author.email_formatted

        return author_id, email_from

    def _message_compute_real_author(self, author_id: int) -> ResPartner:
        real_author = self.env["res.partner"]
        if self.env.user.active:
            real_author = self.env.user.partner_id
        elif author_id:
            author = self.env["res.partner"].browse(author_id)
            if author.active and author != self.env.ref("base.partner_root"):
                real_author = author
        return real_author

    def _message_compute_parent_id(
        self, parent_id: int | Literal[False]
    ) -> int | Literal[False]:
        MailMessage_sudo = self.env["mail.message"].sudo()
        current_ancestor = self.env["mail.message"].sudo()
        if parent_id:
            current_ancestor = MailMessage_sudo.search(
                [
                    ("id", "=", parent_id),
                    ("model", "=", self._name),
                    ("res_id", "=", self.id),
                ],
            )
        if self._mail_flat_thread and not current_ancestor:
            self.env["mail.message"].flush_model(
                ["model", "res_id", "message_type", "date", "create_date"]
            )
            self.env.cr.execute(
                SQL(
                    """
                    SELECT id
                      FROM mail_message
                     WHERE model = %s
                       AND res_id = %s
                       AND message_type != 'user_notification'
                     ORDER BY (message_type IN ('comment', 'email')) DESC,
                              COALESCE(date, create_date) DESC,
                              id DESC
                     LIMIT 1
                    """,
                    self._name,
                    self.id,
                )
            )
            row = self.env.cr.fetchone()
            current_ancestor = MailMessage_sudo.browse(row[0] if row else ())
        return current_ancestor.id

    def _message_compute_subject(self) -> str:
        self.ensure_one()
        return self.display_name

    def _message_create(self, values_list: list[dict]) -> MailMessage:
        values_list = [
            {
                key: val
                for key, val in values.items()
                if key not in self._get_message_create_ignore_field_names()
            }
            for values in values_list
        ]
        create_values_list = []

        self._raise_for_invalid_parameters(
            {key for values in values_list for key in values},
            restricting_names=self._get_message_create_valid_field_names(),
        )

        for values in values_list:
            create_values = dict(values)
            create_values["partner_ids"] = [
                (4, pid) for pid in (create_values.get("partner_ids") or [])
            ]
            create_values_list.append(create_values)

        return (
            self.env["mail.message"]
            .with_context(clean_context(self.env.context))
            .create(create_values_list)
        )

    def _get_message_create_valid_field_names(self) -> set:
        return {
            "attachment_ids",
            "author_guest_id",
            "author_id",
            "body",
            "create_date",
            "date",
            "email_add_signature",
            "email_from",
            "email_layout_xmlid",
            "incoming_email_cc",
            "incoming_email_to",
            "is_internal",
            "mail_activity_type_id",
            "mail_server_id",
            "message_id",
            "message_type",
            "model",
            "outgoing_email_to",
            "parent_id",
            "partner_ids",
            "record_alias_domain_id",
            "record_company_id",
            "reply_to",
            "reply_to_force_new",
            "res_id",
            "subject",
            "subtype_id",
            "tracking_value_ids",
        }

    def _get_message_create_ignore_field_names(self) -> set:
        return set()

    def _get_source_from_ref(self, source_ref: models.BaseModel | str) -> tuple:
        template, view = False, False
        if isinstance(source_ref, models.BaseModel):
            if source_ref._name == "mail.template":
                template = source_ref
            elif source_ref._name == "ir.ui.view":
                view = source_ref
            else:
                raise ValueError(
                    _(
                        "Invalid template or view source record %(svalue)s, is %(model)s instead",
                        svalue=source_ref,
                        model=source_ref._name,
                    )
                )
            if not template and not view:
                raise ValueError(
                    _(
                        "Mailing or posting with a source should not be called with an empty %(source_type)s",
                        source_type=_("template")
                        if template is not False
                        else _("view"),
                    )
                )
        elif isinstance(source_ref, str):
            try:
                res_model, res_id = self.env[
                    "ir.model.data"
                ]._xmlid_to_res_model_res_id(source_ref, raise_if_not_found=True)
            except ValueError as e:
                raise ValueError(
                    _(
                        "Invalid template or view source Xml ID %(source_ref)s does not exist anymore",
                        source_ref=source_ref,
                    )
                ) from e
            if res_model == "mail.template":
                template = self.env["mail.template"].browse(res_id)
            elif res_model == "ir.ui.view":
                view = self.env["ir.ui.view"].browse(res_id)
            else:
                raise ValueError(
                    _(
                        "Invalid template or view source reference %(svalue)s, is %(model)s instead",
                        svalue=source_ref,
                        model=res_model,
                    )
                )
        else:
            raise ValueError(
                _(
                    "Invalid template or view source %(svalue)s (type %(stype)s), should be a record or an XMLID",
                    svalue=source_ref,
                    stype=type(source_ref),
                )
            )
        return template, view

    def _get_notify_valid_parameters(self) -> set:
        valid = {
            "force_email_company",
            "force_email_lang",
            "force_record_name",
            "force_send",
            "mail_auto_delete",
            "model_description",
            "notify_author",
            "notify_author_mention",
            "notify_skip_followers",
            "scheduled_date",
            "send_after_commit",
            "skip_existing",
            "subtitles",
        }
        if not self.env.user.share or self.env.su:
            valid |= {"mail_headers"}
        return valid

    def _notify_get_flag(self, kwargs: dict, param_name: str, context_key: str) -> bool:
        value = kwargs.get(param_name)
        if value is None:
            return bool(self.env.context.get(context_key))
        return bool(value)

    @api.model
    def _is_notification_scheduled(
        self, notify_scheduled_date: str | datetime.datetime | None
    ) -> datetime.datetime | Literal[False]:
        if notify_scheduled_date:
            parsed_datetime = self.env["mail.mail"]._parse_scheduled_datetime(
                notify_scheduled_date
            )
            notify_scheduled_date = (
                parsed_datetime.replace(tzinfo=None) if parsed_datetime else False
            )
        now = self.env.cr.now()
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        return (
            notify_scheduled_date
            if notify_scheduled_date and notify_scheduled_date > now
            else False
        )

    def _raise_for_invalid_parameters(
        self,
        parameter_names: set[str],
        forbidden_names: set[str] | None = None,
        restricting_names: set[str] | None = None,
    ) -> None:
        conflicting_names = set()
        if forbidden_names:
            conflicting_names = parameter_names & forbidden_names
        elif restricting_names:
            conflicting_names = parameter_names - restricting_names
        if conflicting_names:
            raise ValueError(
                _(
                    "Those values are not supported when posting or notifying: %(param_names)s",
                    param_names=", ".join(conflicting_names),
                )
            )

    def _notify_cancel_by_type_generic(self, notification_type: str) -> bool:
        author_id = self.env.user.partner_id.id
        self.env["mail.message"].flush_model(["model"])
        self.env["mail.notification"].flush_model(
            [
                "author_id",
                "mail_message_id",
                "notification_status",
                "notification_type",
            ]
        )
        self.env.cr.execute(
            """
                    SELECT notif.id, msg.id
                      FROM mail_notification notif
                      JOIN mail_message msg ON notif.mail_message_id = msg.id
                      WHERE notif.notification_type = %(notification_type)s
                      AND notif.author_id = %(author_id)s
                      AND notif.notification_status IN ('bounce', 'exception')
                      AND msg.model = %(model_name)s
                """,
            {
                "model_name": self._name,
                "author_id": author_id,
                "notification_type": notification_type,
            },
        )
        records = self.env.cr.fetchall()
        if records:
            notif_ids, msg_ids = zip(*records, strict=True)
            msg_ids = list(set(msg_ids))
            if notif_ids:
                self.env["mail.notification"].browse(notif_ids).sudo().write(
                    {"notification_status": "canceled"}
                )
            if msg_ids:
                self.env["mail.message"].browse(
                    msg_ids
                )._notify_message_notification_update()
        return True

    @api.model
    def notify_cancel_by_type(self, notification_type: str) -> bool:
        if not self.env.user._is_internal():
            raise exceptions.AccessError(_("Access Denied"))
        self.browse().check_access("read")

        if notification_type == "email":
            self._notify_cancel_by_type_generic("email")
        return True

    def _notify_thread(
        self, message: MailMessage, msg_vals: dict | Literal[False] = False, **kwargs
    ) -> list[dict]:
        self = self._fallback_lang()
        self._raise_for_invalid_parameters(
            set(kwargs.keys()), restricting_names=self._get_notify_valid_parameters()
        )

        recipients_data = self._notify_get_recipients(
            message, msg_vals=msg_vals, **kwargs
        )
        uid2pid = {r["uid"]: r["id"] for r in recipients_data if r["id"] and r["uid"]}
        users = self.env["res.users"].browse(uid2pid)
        users._fields["partner_id"]._insert_cache(users, uid2pid.values())

        scheduled_date = self._is_notification_scheduled(
            kwargs.pop("scheduled_date", None)
        )

        if not scheduled_date:
            self._notify_thread_with_out_of_office(
                message, recipients_data, msg_vals=msg_vals, **kwargs
            )

        if not recipients_data:
            return recipients_data

        if scheduled_date:
            self.env["mail.message.schedule"].sudo().create(
                {
                    "scheduled_datetime": scheduled_date,
                    "mail_message_id": message.id,
                    "notification_parameters": self.env[
                        "mail.message.schedule"
                    ]._serialize_notification_parameters(kwargs),
                }
            )
        else:
            self._notify_thread_by_inbox(
                message, recipients_data, msg_vals=msg_vals, **kwargs
            )
            self._notify_thread_by_email(
                message, recipients_data, msg_vals=msg_vals, **kwargs
            )
            self._notify_thread_by_web_push(
                message, recipients_data, msg_vals=msg_vals, **kwargs
            )

        return recipients_data

    def _notify_thread_by_inbox(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        msg_vals: dict | Literal[False] = False,
        **kwargs,
    ) -> None:
        inbox_pids_uids = sorted(
            [
                (r["id"], r["uid"])
                for r in recipients_data
                if r["id"] and r["notif"] == "inbox"
            ]
        )
        if inbox_pids_uids:
            notif_create_values = [
                {
                    "author_id": message.author_id.id,
                    "mail_message_id": message.id,
                    "notification_status": "sent",
                    "notification_type": "inbox",
                    "res_partner_id": pid_uid[0],
                }
                for pid_uid in inbox_pids_uids
            ]
            self.env["mail.notification"].sudo().create(notif_create_values)
            users = self.env["res.users"].browse(i[1] for i in inbox_pids_uids if i[1])
            followers = (
                self.env["mail.followers"]
                .sudo()
                .search(
                    [
                        ("res_model", "=", message.model),
                        ("res_id", "=", message.res_id),
                        ("partner_id", "in", users.partner_id.ids),
                    ]
                )
            )
            starred_pids = self._notify_inbox_get_starred_pids(
                message, [pid for pid, _uid in inbox_pids_uids]
            )
            author_sudo = message.sudo().author_id
            starred_field = message._fields["starred"]
            main_user_field = author_sudo._fields["main_user_id"]
            shared_main_user_id = None
            shared_main_user_computed = False
            for user in users:
                message_for_user = message.with_user(user).with_context(
                    allowed_company_ids=[],
                    mail_notify_inbox=True,
                )
                starred_field._insert_cache(
                    message_for_user, [user.partner_id.id in starred_pids]
                )
                if author_sudo and author_sudo.id != user.partner_id.id:
                    author_for_user = message_for_user.sudo().author_id
                    if not shared_main_user_computed:
                        shared_main_user_id = author_for_user.main_user_id.id or None
                        shared_main_user_computed = True
                    else:
                        main_user_field._insert_cache(
                            author_for_user, [shared_main_user_id]
                        )
                store = Store(bus_channel=user).add(
                    message_for_user,
                    msg_vals=msg_vals,
                    add_followers=True,
                    followers=followers,
                )
                user._bus_send(
                    "mail.message/inbox",
                    {
                        "message_id": message.id,
                        "store_data": store.get_result(),
                    },
                )

    def _notify_inbox_get_starred_pids(
        self, message: MailMessage, partner_ids: list[int]
    ) -> frozenset[int]:
        if not partner_ids:
            return frozenset()
        self.env["mail.message"].flush_model(["starred_partner_ids"])
        self.env.cr.execute(
            """
            SELECT res_partner_id
              FROM mail_message_res_partner_starred_rel
             WHERE mail_message_id = %s AND res_partner_id = ANY(%s)
            """,
            (message.id, list(partner_ids)),
        )
        return frozenset(pid for [pid] in self.env.cr.fetchall())

    def _notify_thread_by_email(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        *,
        msg_vals: dict | Literal[False] = False,
        mail_auto_delete: bool = True,
        model_description: str | Literal[False] = False,
        force_email_company: ResCompany | Literal[False] = False,
        force_email_lang: str | Literal[False] = False,
        force_record_name: str | Literal[False] = False,
        subtitles: list[str] | None = None,
        force_send: bool = True,
        send_after_commit: bool = True,
        **kwargs,
    ) -> bool:
        partners_data = [r for r in recipients_data if r["notif"] == "email"]
        if not partners_data:
            return True

        additional_values = {"auto_delete": mail_auto_delete}
        if kwargs.get("mail_headers"):
            additional_values["headers"] = kwargs["mail_headers"]
        base_mail_values = self._notify_by_email_get_base_mail_values(
            message,
            partners_data,
            additional_values=additional_values,
        )
        base_notification_values = self._notify_by_email_get_base_notification_values(
            message
        )

        SafeMail = (
            self.env["mail.mail"].sudo().with_context(clean_context(self.env.context))
        )
        SafeNotification = (
            self.env["mail.notification"]
            .sudo()
            .with_context(clean_context(self.env.context))
        )
        gen_batch_size = (
            self.env["ir.config_parameter"]._get_int_param("mail.batch_size", 50) or 50
        )
        mail_values_list = []
        notif_targets = []
        for (
            _lang,
            render_values,
            recipients_group,
        ) in self._notify_get_classified_recipients_iterator(
            message,
            partners_data,
            msg_vals=msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
            force_record_name=force_record_name,
            subtitles=subtitles,
        ):
            mail_body = self._notify_by_email_render_layout(
                message,
                recipients_group,
                msg_vals=msg_vals,
                render_values=render_values,
            )
            recipients_emails = recipients_group["recipients_emails"]
            recipients_ids = recipients_group["recipients_ids"]

            for recipients_ids_chunk in batched(
                recipients_ids, gen_batch_size, strict=False
            ):
                mail_values_list.append(
                    self._notify_by_email_get_final_mail_values(
                        recipients_ids_chunk,
                        base_mail_values,
                        additional_values={"body_html": mail_body},
                    )
                )
                notif_targets.append(("res_partner_id", recipients_ids_chunk))
            if recipients_emails:
                mail_values = self._notify_by_email_get_final_mail_values(
                    [],
                    base_mail_values,
                    additional_values={"body_html": mail_body},
                )
                mail_values["email_to"] = ",".join(recipients_emails)
                mail_values_list.append(mail_values)
                notif_targets.append(("mail_email_address", recipients_emails))

        emails = SafeMail.create(mail_values_list)
        notif_create_values = [
            {
                "mail_mail_id": mail.id,
                target_field: target,
                **base_notification_values,
            }
            for mail, (target_field, targets) in zip(emails, notif_targets, strict=True)
            for target in targets
        ]

        if notif_create_values:
            SafeNotification.create(notif_create_values)

        if force_send := self.env.context.get("mail_notify_force_send", force_send):
            force_send_limit = self.env["ir.config_parameter"]._get_int_param(
                "mail.mail.force.send.limit", 100
            )
            force_send = len(emails) < force_send_limit
        if force_send:
            if send_after_commit:
                emails.send_after_commit()
            else:
                emails.send()

        return True

    def _notify_get_classified_recipients_iterator(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        msg_vals: dict | Literal[False] = False,
        model_description: str | Literal[False] = False,
        force_email_company: ResCompany | Literal[False] = False,
        force_email_lang: str | Literal[False] = False,
        force_record_name: str | Literal[False] = False,
        subtitles: list[str] | None = None,
    ) -> Iterator[tuple]:
        lang_to_recipients = {}
        for data in recipients_data:
            if lang_code := data.get("lang"):
                lang_code = (
                    bool(self.env["res.lang"]._lang_get(lang_code)) and lang_code
                )
            lang_to_recipients.setdefault(
                lang_code or force_email_lang or self.env.lang,
                [],
            ).append(data)

        for lang, lang_recipients_data in lang_to_recipients.items():
            record_wlang = self.with_context(lang=lang)
            lang_model_description = model_description
            if not lang_model_description:
                lang_model_description = record_wlang._get_model_description(
                    (msg_vals and msg_vals.get("model")) or message.model
                )
            recipients_groups_list = record_wlang._notify_get_recipients_classify(
                message,
                lang_recipients_data,
                lang_model_description,
                msg_vals=msg_vals,
            )
            render_values = record_wlang._notify_by_email_prepare_rendering_context(
                message,
                msg_vals=msg_vals,
                model_description=lang_model_description,
                force_email_company=force_email_company,
                force_email_lang=lang,
                force_record_name=force_record_name,
            )
            if subtitles:
                render_values["subtitles"] = subtitles

            for recipients_group in recipients_groups_list:
                group_render_values = render_values
                if not render_values["show_unfollow"] and any(
                    r["is_follower"]
                    for r in recipients_group["recipients_data"]
                    if r["id"] and r["uid"] and not r["ushare"]
                ):
                    group_render_values = {**render_values, "show_unfollow": True}
                yield (lang, group_render_values, recipients_group)

    def _notify_by_email_prepare_rendering_context(
        self,
        message: MailMessage,
        msg_vals: dict | Literal[False] = False,
        model_description: str | Literal[False] = False,
        force_email_company: ResCompany | Literal[False] = False,
        force_email_lang: str | Literal[False] = False,
        force_record_name: str | Literal[False] = False,
    ) -> dict:
        msg_vals = msg_vals or {}

        lang = force_email_lang or self.env.lang
        record_wlang = self.with_context(lang=lang)

        author = (
            message.env["res.partner"].browse(msg_vals.get("author_id"))
            if "author_id" in msg_vals
            else message.author_id
        )
        author_user = author.main_user_id
        signature, email_add_signature = "", False

        if author_user:
            email_add_signature = msg_vals.get(
                "email_add_signature", message.email_add_signature
            )
            if email_add_signature:
                signature = Markup("<div>-- <br/>%s</div>") % author_user.signature

        if force_email_company:
            company = force_email_company
        else:
            company = (
                record_wlang.company_id.sudo()
                if (
                    record_wlang
                    and "company_id" in record_wlang
                    and record_wlang.company_id
                )
                else record_wlang.env.company
            )
        if company.website:
            website_url = (
                "http://%s" % company.website
                if not company.website.lower().startswith(("http:", "https:"))
                else company.website
            )
        else:
            website_url = False

        if not model_description:
            model_description = record_wlang._get_model_description(
                msg_vals.get("model", message.model)
            )
        record_name = force_record_name or message.with_context(lang=lang).record_name

        check_tracking = (
            msg_vals.get("tracking_value_ids", True) if msg_vals else bool(self)
        )
        tracking = []
        if check_tracking:
            tracking_values = (
                self.env["mail.tracking.value"]
                .sudo()
                .search([("mail_message_id", "in", message.ids)])
                ._filter_has_field_access(self.env)
            )
            if tracking_values:
                tracking_values = record_wlang._track_filter_for_display(
                    tracking_values
                )
            tracking = [
                (
                    fmt_vals["fieldInfo"]["changedField"],
                    fmt_vals["oldValue"],
                    fmt_vals["newValue"],
                )
                for fmt_vals in tracking_values._tracking_value_format()
            ]

        subtype_id = msg_vals.get("subtype_id", message.subtype_id.id)
        is_discussion = subtype_id == self.env["ir.model.data"]._xmlid_to_res_id(
            "mail.mt_comment"
        )

        return {
            "is_discussion": is_discussion,
            "message": message,
            "subtype": message.subtype_id,
            "tracking_values": tracking,
            "model_description": model_description,
            "record": record_wlang,
            "record_name": record_name,
            "subtitles": [record_name],
            "author_user": author_user,
            "company": company,
            "email_add_signature": email_add_signature,
            "lang": lang,
            "show_unfollow": getattr(self, "_partner_unfollow_enabled", False),
            "signature": signature,
            "website_url": website_url,
            "is_html_empty": is_html_empty,
            "email_notification_force_header": self.env.context.get(
                "email_notification_force_header", False
            ),
            "email_notification_force_footer": self.env.context.get(
                "email_notification_force_footer", False
            ),
            "email_notification_allow_header": self.env.context.get(
                "email_notification_allow_header", True
            ),
            "email_notification_allow_footer": self.env.context.get(
                "email_notification_allow_footer", False
            ),
        }

    def _notify_by_email_render_layout(
        self,
        message: MailMessage,
        recipients_group: dict,
        msg_vals: dict | Literal[False] = False,
        render_values: dict | None = None,
    ) -> Markup:
        if render_values is None:
            render_values = {}
        msg_vals = msg_vals or {}

        email_layout_xmlid = msg_vals.get(
            "email_layout_xmlid", message.email_layout_xmlid
        )
        template_xmlid = email_layout_xmlid or "mail.mail_notification_layout"

        render_values = {**render_values, **recipients_group}
        mail_body = self.env["ir.qweb"]._render(
            template_xmlid,
            render_values,
            minimal_qcontext=True,
            raise_if_not_found=False,
            lang=render_values.get("lang", self.env.lang),
        )
        if not mail_body:
            _logger.warning(
                "QWeb template %s not found or is empty when sending notification emails. Sending without layouting.",
                template_xmlid,
            )
            mail_body = message.body
        return mail_body

    def _notify_by_email_get_base_mail_values(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        additional_values: dict | None = None,
    ) -> dict:
        mail_subject = message.subject
        if not mail_subject and self:
            mail_subject = self._message_compute_subject()
        if not mail_subject:
            mail_subject = message.record_name
        if mail_subject:
            mail_subject = " ".join(mail_subject.splitlines())

        message_sudo = message.sudo()
        ancestors = (
            self.env["mail.message"]
            .sudo()
            .search(
                [
                    ("model", "=", message_sudo.model),
                    ("res_id", "=", message_sudo.res_id),
                    ("id", "!=", message_sudo.id),
                    ("subtype_id", "!=", False),
                    (
                        "message_id",
                        "!=",
                        False,
                    ),
                ],
                limit=32,
                order="id DESC",
            )
        )

        outgoing_types = ("comment", "auto_comment", "email", "email_outgoing")
        history_ancestors = ancestors.sorted(
            lambda m: (
                not m.is_internal and not m.subtype_id.internal,
                m.message_type in outgoing_types,
                m.message_type
                not in (
                    "user_notification",
                    "out_of_office",
                ),
            ),
            reverse=True,
        )
        ancestors = history_ancestors[:3].sorted("id")
        references = " ".join(m.message_id for m in (ancestors + message_sudo))
        base_mail_values = {
            "mail_message_id": message.id,
            "references": references,
        }
        if mail_subject != message.subject:
            base_mail_values["subject"] = mail_subject
        if additional_values:
            base_mail_values.update(additional_values)

        headers = dict(base_mail_values.get("headers") or {})
        external_emails = [
            formataddr((r["name"], r["email_normalized"]))
            for r in recipients_data
            if r["active"] and r["email_normalized"] and r["share"]
        ]
        external_emails_normalized = [
            r["email_normalized"]
            for r in recipients_data
            if r["active"] and r["email_normalized"] and r["share"]
        ]
        external_emails += list(
            {
                email
                for email in email_split_and_format_normalize(
                    f"{message_sudo.incoming_email_to or ''},{message_sudo.incoming_email_cc or ''}"
                )
                if email_normalize(email) not in external_emails_normalized
            }
        )
        if (
            external_emails
            and len(external_emails) < self._CUSTOMER_HEADERS_LIMIT_COUNT
        ):
            headers["X-Msg-To-Add"] = ",".join(external_emails)
        if message_sudo.record_alias_domain_id.bounce_email:
            headers["Return-Path"] = message_sudo.record_alias_domain_id.bounce_email
        headers = self._notify_by_email_get_headers(headers=headers)
        if headers:
            base_mail_values["headers"] = repr(headers)
        return base_mail_values

    def _notify_by_email_get_final_mail_values(
        self,
        recipient_ids: Sequence[int],
        mail_values: dict,
        additional_values: dict | None = None,
    ) -> dict:
        final_mail_values = dict(mail_values)
        final_mail_values["recipient_ids"] = [(4, pid) for pid in recipient_ids]
        if additional_values:
            final_mail_values.update(additional_values)
        return final_mail_values

    def _notify_by_email_get_base_notification_values(
        self, message: MailMessage
    ) -> dict:
        return {
            "author_id": message.author_id.id,
            "is_read": True,
            "mail_message_id": message.id,
            "notification_status": "ready",
            "notification_type": "email",
        }

    def _notify_thread_by_web_push(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        msg_vals: dict | Literal[False] = False,
        **kwargs,
    ) -> None:
        partner_ids = self._notify_get_recipients_for_extra_notifications(
            message, recipients_data, msg_vals=msg_vals
        )
        devices, private_key, public_key = self._web_push_get_partners_parameters(
            partner_ids
        )
        if not devices:
            return
        payload = self._web_push_truncate_payload(
            self._notify_by_web_push_prepare_payload(
                message,
                msg_vals=msg_vals,
                force_record_name=kwargs.get("force_record_name"),
            )
        )
        self._web_push_send_notification(
            devices, private_key, public_key, payload=payload
        )

    def _web_push_get_partners_parameters(self, partner_ids: list[int]) -> tuple:
        devices_su = self.env["mail.push.device"].sudo()
        if not partner_ids:
            return devices_su, None, None
        vapid_private_key = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.web_push_vapid_private_key")
        )
        vapid_public_key = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.web_push_vapid_public_key")
        )
        if not vapid_private_key or not vapid_public_key:
            return devices_su, None, None
        return (
            devices_su.search([("partner_id", "in", partner_ids)]),
            vapid_private_key,
            vapid_public_key,
        )

    def _web_push_send_notification(
        self,
        devices: MailPushDevice,
        private_key: str | None,
        public_key: str | None,
        payload_by_lang: dict | None = None,
        payload: dict | None = None,
    ) -> None:
        if len(devices) < MAX_DIRECT_PUSH:
            session = Session()
            devices_to_unlink = set()
            for device in devices:
                try:
                    push_to_end_point(
                        base_url=self.get_base_url(),
                        device={
                            "id": device.id,
                            "endpoint": device.endpoint,
                            "keys": device.keys,
                        },
                        payload=json.dumps(
                            (
                                payload_by_lang
                                and payload_by_lang.get(device.partner_id.lang)
                            )
                            or payload
                        ),
                        vapid_private_key=private_key,
                        vapid_public_key=public_key,
                        session=session,
                    )
                except DeviceUnreachableError:
                    devices_to_unlink.add(device.id)
                except PushEndpointUnresolvableError:
                    _logger.info(
                        "Push endpoint temporarily unresolvable, keeping device %s",
                        device.id,
                    )
                except Exception as e:  # pylint: disable=broad-except
                    _logger.error(
                        "An error occurred while contacting the endpoint: %s", e
                    )

            if devices_to_unlink:
                devices_list = list(devices_to_unlink)
                self.env["mail.push.device"].sudo().browse(devices_list).unlink()

        else:
            self.env["mail.push"].sudo().create(
                [
                    {
                        "mail_push_device_id": device.id,
                        "payload": json.dumps(
                            (
                                payload_by_lang
                                and payload_by_lang.get(device.partner_id.lang)
                            )
                            or payload
                        ),
                    }
                    for device in devices
                ]
            )
            self.env.ref("mail.ir_cron_web_push_notification")._trigger()

    def _notify_by_web_push_prepare_payload(
        self,
        message: MailMessage,
        msg_vals: dict | Literal[False] = False,
        force_record_name: str | Literal[False] = False,
    ) -> dict:
        msg_vals = msg_vals or {}
        author_id = msg_vals.get("author_id", message.author_id.id)
        model = msg_vals.get("model", message.model)
        title = force_record_name or message.record_name
        res_id = msg_vals.get("res_id", message.res_id)
        body = msg_vals.get("body", message.body)

        if author_id:
            author_name = self.env["res.partner"].browse(author_id).name
            title = "%s: %s" % (author_name, title)
            icon = "/web/image/res.partner/%d/avatar_128" % author_id
        else:
            icon = "/web/static/img/odoo-icon-192x192.png"

        if tools.is_html_empty(body) and message.attachment_ids:
            total_attachments = len(message.attachment_ids)
            attachments = message.attachment_ids.sudo()

            def get_attachment_label(attachment: IrAttachment) -> str:
                return (
                    self.env._("Voice Message")
                    if attachment.voice_ids
                    else attachment.name
                )

            if total_attachments == 1:
                body = get_attachment_label(attachments[0])
            elif total_attachments == 2:
                body = self.env._(
                    "%(file1)s and %(file2)s",
                    file1=get_attachment_label(attachments[0]),
                    file2=get_attachment_label(attachments[1]),
                )
            else:
                body = self.env._(
                    "%(file1)s and %(count)d other attachments",
                    file1=get_attachment_label(attachments[0]),
                    count=total_attachments - 1,
                )

        return {
            "title": title,
            "options": {
                "body": html2plaintext(body, include_references=False)
                + self._generate_tracking_message(message),
                "icon": icon,
                "data": {
                    "model": model or "",
                    "res_id": res_id or "",
                },
            },
        }

    def _notify_get_recipients(
        self, message: MailMessage, msg_vals: dict | Literal[False] = False, **kwargs
    ) -> list[dict]:
        msg_vals = msg_vals or {}
        msg_sudo = message.sudo()

        pids = msg_vals.get("partner_ids", msg_sudo.partner_ids.ids)
        if kwargs.get("notify_skip_followers"):
            message_type = "user_notification"
        else:
            message_type = msg_vals.get("message_type", msg_sudo.message_type)
        subtype_id = msg_vals.get("subtype_id", msg_sudo.subtype_id.id)

        recipients_data = []
        res = self.env["mail.followers"]._get_recipient_data(
            self, message_type, subtype_id, pids
        )[self.id if self else 0]
        outgoing_email_to_lst = email_split_and_normalize(
            msg_vals.get("outgoing_email_to", msg_sudo.outgoing_email_to)
        )
        if not res and not outgoing_email_to_lst:
            return recipients_data

        skip_author_id = False
        notify_author = self._notify_get_flag(
            kwargs, "notify_author", "mail_notify_author"
        )
        if not notify_author:
            notify_author_mention = self._notify_get_flag(
                kwargs, "notify_author_mention", "mail_notify_author_mention"
            )
            author_id = msg_vals.get("author_id") or message.author_id.id
            skip_author_id = self._message_compute_real_author(author_id).id
            if notify_author_mention and skip_author_id in pids:
                skip_author_id = False

        emailed_normalized = set(
            email_normalize_all(
                f"{msg_vals.get('incoming_email_to', msg_sudo.incoming_email_to) or ''}, "
                f"{msg_vals.get('incoming_email_cc', msg_sudo.incoming_email_cc) or ''}"
            )
        )
        emailed_normalized_covered = set(emailed_normalized)

        for pid, pdata in res.items():
            if pid and pid == skip_author_id:
                continue
            if pdata["active"] is False:
                continue
            if (
                pdata["notif"] == "email"
                and pdata["email_normalized"] in emailed_normalized
            ):
                continue
            recipients_data.append(pdata)
            if pdata["notif"] == "email" and pdata["email_normalized"]:
                emailed_normalized_covered.add(pdata["email_normalized"])

        for name, email_address in outgoing_email_to_lst:
            if not email_address or email_address in emailed_normalized_covered:
                continue
            emailed_normalized_covered.add(email_address)
            recipients_data.append(
                {
                    "active": True,
                    "email_normalized": email_address,
                    "id": False,
                    "is_follower": False,
                    "name": name or email_address,
                    "lang": False,
                    "groups": [],
                    "notif": "email",
                    "share": True,
                    "type": "customer",
                    "uid": False,
                    "ushare": False,
                }
            )

        if kwargs.pop("skip_existing", False):
            pids = [r["id"] for r in recipients_data if r["id"]]
            emails = [
                r["email_normalized"]
                for r in recipients_data
                if not r["id"] and r["email_normalized"]
            ]
            if pids or emails:
                existing_notifications = (
                    self.env["mail.notification"]
                    .sudo()
                    .search(
                        [
                            ("mail_message_id", "in", message.ids),
                            "|",
                            ("res_partner_id", "in", pids),
                            ("mail_email_address", "in", emails),
                        ]
                    )
                )
                existing_pids = set(existing_notifications.res_partner_id.ids)
                existing_emails = set(
                    existing_notifications.mapped("mail_email_address")
                )
                recipients_data = [
                    r
                    for r in recipients_data
                    if (
                        r["id"] not in existing_pids
                        if r["id"]
                        else r["email_normalized"] not in existing_emails
                    )
                ]

        return recipients_data

    def _notify_get_recipients_groups(
        self,
        message: MailMessage,
        model_description: str,
        msg_vals: dict | Literal[False] = False,
    ) -> list:
        return [
            [
                "user",
                lambda pdata: pdata["type"] == "user",
                {
                    "active": True,
                    "has_button_access": self.env["mail.message"]._is_thread_message(
                        vals=msg_vals, thread=self
                    ),
                },
            ],
            [
                "portal",
                lambda pdata: pdata["type"] == "portal",
                {
                    "active": False,
                    "has_button_access": False,
                },
            ],
            [
                "follower",
                lambda pdata: pdata["is_follower"],
                {
                    "active": False,
                    "has_button_access": False,
                },
            ],
            [
                "customer",
                lambda pdata: True,
                {
                    "active": True,
                    "has_button_access": False,
                },
            ],
        ]

    def _notify_get_recipients_groups_fillup(
        self,
        groups: list,
        model_description: str,
        msg_vals: dict | Literal[False] = False,
    ) -> list:
        access_link = self._notify_get_action_link("view", **msg_vals)

        if model_description:
            view_title = _("View %s", model_description)
        else:
            view_title = _("View")

        is_thread_message = self.env["mail.message"]._is_thread_message(
            vals=msg_vals, thread=self
        )

        for group_name, _group_func, group_data in groups:
            group_data.setdefault("active", True)
            group_data.setdefault("has_button_access", is_thread_message)
            group_data.setdefault("notification_group_name", group_name)
            group_data.setdefault("recipients_data", [])
            group_data.setdefault("recipients_emails", [])
            group_data.setdefault("recipients_ids", [])
            group_button_access = group_data.setdefault("button_access", {})
            group_button_access.setdefault("url", access_link)
            group_button_access.setdefault("title", view_title)

        return groups

    def _notify_get_recipients_classify(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        model_description: str,
        msg_vals: dict | Literal[False] = False,
    ) -> list:
        local_msg_vals = dict(msg_vals) if msg_vals else {}
        groups = self._notify_get_recipients_groups_fillup(
            self._notify_get_recipients_groups(
                message, model_description, msg_vals=local_msg_vals
            ),
            model_description,
            msg_vals=local_msg_vals,
        )
        for _group_name, _group_func, group_data in groups:
            if "actions" in group_data:
                _logger.warning("Invalid usage of actions in notification groups")

        for recipient_data in recipients_data:
            for _group_name, group_func, group_data in groups:
                if group_data["active"] and group_func(recipient_data):
                    group_data["recipients_data"].append(recipient_data)
                    if recipient_data["id"]:
                        group_data["recipients_ids"].append(recipient_data["id"])
                    elif recipient_data["email_normalized"]:
                        group_data["recipients_emails"].append(
                            recipient_data["email_normalized"]
                        )
                    break

        return [
            group_data
            for _group_name, _group_func, group_data in groups
            if group_data["recipients_data"]
        ]

    def _notify_get_recipients_for_extra_notifications(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        msg_vals: dict | Literal[False] = False,
    ) -> set[int]:
        msg_vals = msg_vals or {}
        msg_sudo = message.sudo()
        emailed_normalized = set(
            email_normalize_all(
                f"{msg_vals.get('incoming_email_to', msg_sudo.incoming_email_to) or ''}, "
                f"{msg_vals.get('incoming_email_cc', msg_sudo.incoming_email_cc) or ''}"
            )
        )
        notif_pids = []
        notif_pids_notinbox = []
        for recipient in (r for r in recipients_data if r["active"] and r["id"]):
            if (
                emailed_normalized
                and recipient["email_normalized"] in emailed_normalized
            ):
                continue
            notif_pids.append(recipient["id"])
            if recipient["notif"] != "inbox":
                notif_pids_notinbox.append(recipient["id"])
        if not notif_pids:
            return set()

        msg_type = msg_vals.get("message_type") or msg_sudo.message_type
        author_ids = [msg_vals.get("author_id") or msg_sudo.author_id.id]
        if msg_type in {"comment", "whatsapp_message"}:
            return set(notif_pids) - set(author_ids)
        elif msg_type in ("notification", "user_notification", "email"):
            return set(notif_pids) - set(author_ids) - set(notif_pids_notinbox)
        return set()

    def _notify_get_action_link(self, link_type: str, **kwargs) -> str:
        params = self._get_action_link_params(link_type, **kwargs)

        if link_type in ["view", "unfollow"]:
            base_link = "/mail/%s" % link_type
        elif link_type == "controller":
            controller = kwargs.get("controller")
            base_link = "%s" % controller
        else:
            raise NotImplementedError(f"Invalid notification link type {link_type}")

        if link_type != "view":
            token = self._encode_link(base_link, params)
            params["token"] = token

        link = "%s?%s" % (base_link, urlencode(sorted(params.items())))
        if self:
            link = self[0].get_base_url() + link

        return link

    def _notify_thread_with_out_of_office(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        msg_vals: dict | Literal[False] = False,
        **kwargs,
    ) -> MailMessage:
        ooo_messages = self.env["mail.message"]
        if not self or self._transient:
            return ooo_messages
        message_type = (
            msg_vals["message_type"]
            if "message_type" in (msg_vals or {})
            else message.message_type
        )
        if message_type not in ("comment", "email"):
            return ooo_messages

        trigger_is_internal = bool(
            msg_vals["is_internal"]
            if "is_internal" in (msg_vals or {})
            else message.is_internal
        )

        recipient = self._message_compute_real_author(
            (msg_vals or {}).get("author_id") or message.author_id.id
        ).sudo()
        email_to = (
            ((msg_vals or {}).get("email_from") or message.email_from)
            if not recipient
            else False
        )
        if not recipient and not email_to:
            return ooo_messages

        pids = (
            msg_vals["partner_ids"]
            if "partner_ids" in (msg_vals or {})
            else message.partner_ids.ids
        )
        internal_uids = [
            r["uid"]
            for r in recipients_data
            if (
                r["active"]
                and r["id"]
                and r["id"] in pids
                and r["id"] not in recipient.ids
                and r["uid"]
                and not r["share"]
            )
        ]
        additional_users_su = (
            self._notify_thread_with_out_of_office_get_additional_users(
                message,
                recipients_data,
                recipient,
                msg_vals=msg_vals,
            )
        )
        users_to_check = (
            self.env["res.users"].sudo().browse(internal_uids) | additional_users_su
        )
        ooo_users = self.env["res.users"].sudo()
        if users_to_check:
            users_to_check.fetch(["is_out_of_office", "out_of_office_message"])
            ooo_users = users_to_check.filtered(
                lambda u: (
                    u.is_out_of_office and not is_html_empty(u.out_of_office_message)
                )
            )
        if not ooo_users:
            return ooo_messages

        exchange_domain = Domain.OR(
            ([Domain("partner_ids", "in", recipient.ids)] if recipient else [])
            + ([Domain("outgoing_email_to", "=", email_to)] if email_to else [])
        )
        sent_su = (
            self.env["mail.message"]
            .sudo()
            .search(
                Domain(
                    [
                        ("author_id", "in", ooo_users.partner_id.ids),
                        ("message_type", "=", "out_of_office"),
                        ("date", ">=", "-4d"),
                    ]
                )
                & exchange_domain
            )
        )
        already_mailed = sent_su.author_id

        original_subject = (
            msg_vals["subject"] if "subject" in (msg_vals or {}) else message.subject
        )
        for user in ooo_users.filtered(lambda u: u.partner_id not in already_mailed):
            body = self.env["ir.qweb"]._render(
                "mail.message_notification_out_of_office",
                {
                    "out_of_office_message": user.out_of_office_message,
                    "replied_body": msg_vals["body"]
                    if "body" in (msg_vals or {})
                    else message.body,
                    "signature": user.signature,
                    "is_html_empty": is_html_empty,
                },
                minimal_qcontext=True,
                raise_if_not_found=False,
            )
            ooo_messages += self.sudo().message_post(
                author_id=user.partner_id.id,
                body=body,
                email_from=user.email_formatted,
                mail_headers={
                    "Auto-Submitted": "auto-replied",
                    "X-Auto-Response-Suppress": "All",
                },
                message_type="out_of_office",
                notify_author=True,
                notify_skip_followers=True,
                outgoing_email_to=email_to,
                partner_ids=recipient.ids,
                is_internal=trigger_is_internal,
                subject=_(
                    "Auto: %(subject)s", subject=(original_subject or self.display_name)
                ),
                subtype_id=self.env.ref(
                    "mail.mt_note" if trigger_is_internal else "mail.mt_comment"
                ).id,
            )
        return ooo_messages

    def _notify_thread_with_out_of_office_get_additional_users(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        ooo_author: ResPartner,
        msg_vals: dict | Literal[False] = False,
    ) -> ResUsers:
        pids = [r["id"] for r in recipients_data if r["id"]]
        additional_users_su = self.env["res.users"].sudo()
        if self and "user_id" in self:
            additional_users_su += self.user_id.sudo().filtered(
                lambda u: u.partner_id != ooo_author
            )

        parent_msg = self.env["mail.message"].sudo()
        if (msg_vals or {}).get("parent_id"):
            parent_msg = self.env["mail.message"].sudo().browse(msg_vals["parent_id"])
        elif "parent_id" not in (msg_vals or {}):
            parent_msg = message.parent_id
        parent_author = (
            parent_msg.author_id
            if parent_msg.author_id.active
            else self.env["res.partner"]
        )
        if (
            parent_author
            and parent_author.id not in pids
            and parent_author != ooo_author
            and not parent_msg.author_id.partner_share
        ):
            additional_users_su |= parent_msg.author_id.main_user_id
        return additional_users_su

    @api.model
    def _encode_link(self, base_link: str, params: dict) -> str:
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        token = "%s?%s" % (
            base_link,
            " ".join("%s=%s" % (key, params[key]) for key in sorted(params)),
        )
        return hmac.new(
            secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha1
        ).hexdigest()

    def _get_action_link_params(self, link_type: str, **kwargs) -> dict:
        params = {
            "model": kwargs.get("model", self._name),
            "res_id": kwargs.get("res_id", self.ids[0] if self else False),
        }
        params.update(
            {
                key: value
                for key, value in kwargs.items()
                if value is not None
                and key
                in (
                    "action",
                    "token",
                    "access_token",
                    "auth_signup_token",
                    "auth_login",
                    "pid",
                    "hash",
                )
            }
        )
        if link_type == "controller":
            params.pop("model")
        elif link_type not in ("view", "unfollow"):
            return {}
        return params

    @api.model
    def _generate_tracking_message(
        self, message: MailMessage, return_line: str = "\n"
    ) -> str:
        tracking_message = ""
        if message.subtype_id and message.subtype_id.description:
            tracking_message = (
                return_line + message.subtype_id.description + return_line
            )

        def _fmt(value: Any, is_bool: bool) -> str:
            if is_bool:
                return str(bool(value))
            return "" if value is None or value is False else str(value)

        trackings = message.sudo().tracking_value_ids._filter_free_field_access()
        for formatted in trackings._tracking_value_format():
            is_bool = formatted["fieldInfo"]["fieldType"] == "boolean"
            old_value = _fmt(formatted["oldValue"], is_bool)
            new_value = _fmt(formatted["newValue"], is_bool)
            tracking_message += (
                formatted["fieldInfo"]["changedField"] + ": " + old_value
            )
            if old_value != new_value:
                tracking_message += " → " + new_value
            tracking_message += return_line

        return tracking_message

    @api.model
    def _get_model_description(self, model_name: str) -> str | Literal[False]:
        if not model_name:
            return False
        if "lang" not in self.env.context:
            raise ValueError(_("At this point lang should be correctly set"))
        return self.env["ir.model"]._get(model_name).display_name

    @api.model
    def _web_push_truncate_payload(self, payload: dict) -> dict:
        payload_length = len(json.dumps(payload).encode())
        body = json.dumps(payload["options"]["body"])[1:-1]
        body_length = len(body)

        max_length = self._truncate_payload_get_max_payload_length()
        if payload_length > max_length:
            body_max_length = max(0, max_length - payload_length + body_length)
            try:
                truncated_body = body[:body_max_length].rstrip("\\")
                truncated_body = json.loads(f'"{truncated_body}"')
            except json.decoder.JSONDecodeError as json_error:
                truncated_body = json.loads(f'"{body[: json_error.pos - 2]}"')
            payload["options"]["body"] = truncated_body
        return payload

    @staticmethod
    def _truncate_payload_get_max_payload_length() -> int:
        return MAX_PAYLOAD_SIZE - ENCRYPTION_HEADER_SIZE - ENCRYPTION_BLOCK_OVERHEAD

    def message_subscribe(
        self, partner_ids: list[int] | None = None, subtype_ids: list[int] | None = None
    ) -> bool:
        if not self or not partner_ids:
            return True

        adding_current = set(partner_ids) == {self.env.user.partner_id.id}
        customer_ids = [] if adding_current else None

        if adding_current:
            try:
                self.check_access("read")
            except exceptions.AccessError:
                return False
        else:
            self.check_access("write")

        if not adding_current:
            partner_ids = (
                self.env["res.partner"]
                .sudo()
                .search([("id", "in", partner_ids), ("active", "=", True)])
                .ids
            )

        return self._message_subscribe(
            partner_ids, subtype_ids, customer_ids=customer_ids
        )

    def _message_subscribe(
        self,
        partner_ids: list[int] | None = None,
        subtype_ids: list[int] | None = None,
        customer_ids: list[int] | None = None,
    ) -> bool:
        if not self:
            return True

        if not subtype_ids:
            self.env["mail.followers"]._add_followers(
                self._name,
                self.ids,
                partner_ids,
                subtypes=None,
                customer_ids=customer_ids,
                check_existing=True,
                existing_policy="skip",
            )
        else:
            self.env["mail.followers"]._add_followers(
                self._name,
                self.ids,
                partner_ids,
                subtypes=dict.fromkeys(partner_ids, subtype_ids),
                customer_ids=customer_ids,
                check_existing=True,
                existing_policy="replace",
            )

        return True

    def message_unsubscribe(self, partner_ids: list[int] | None = None) -> bool:
        if not partner_ids:
            return True
        if set(partner_ids) != {self.env.user.partner_id.id}:
            self.check_access("write")
        elif not self.env.user._is_internal():
            self.check_access("read")
        self.env["mail.followers"].sudo().search(
            [
                ("res_model", "=", self._name),
                ("res_id", "in", self.ids),
                ("partner_id", "in", partner_ids),
            ]
        ).unlink()
        return True

    def _message_auto_subscribe_followers(
        self, updated_values: dict, default_subtype_ids: list[int]
    ) -> list:
        field = self._fields.get("user_id")
        user_id = updated_values.get("user_id")
        if (
            field
            and user_id
            and field.comodel_name == "res.users"
            and getattr(field, "tracking", False)
        ):
            user = self.env["res.users"].sudo().browse(user_id)
            try:
                if user.active:
                    return [
                        (
                            user.partner_id.id,
                            default_subtype_ids,
                            "mail.message_user_assigned"
                            if user != self.env.user
                            else False,
                        )
                    ]
            except Exception:  # noqa: S110
                pass
        return []

    def _message_auto_subscribe_notify(
        self, partner_ids: list[int], template: str
    ) -> None:
        if not self or self.env.context.get("mail_auto_subscribe_no_notify"):
            return
        if not self.env.registry.ready:
            return
        if self.env.context.get("install_demo"):
            return

        model_description = self.env["ir.model"]._get(self._name).display_name
        has_company = "company_id" in self
        IrQweb = self.env["ir.qweb"]
        RenderMixin = self.env["mail.render.mixin"]
        bodies, subjects = {}, {}
        for record in self:
            company = record.company_id.sudo() if has_company else self.env.company
            values = {
                "access_link": record._notify_get_action_link("view"),
                "company": company,
                "model_description": model_description,
                "object": record,
            }
            assignation_msg = IrQweb._render(template, values, minimal_qcontext=True)
            bodies[record.id] = RenderMixin._replace_local_links(assignation_msg)
            subjects[record.id] = _("You have been assigned to %s", record.display_name)
        self._message_notify_batch(
            bodies,
            subjects=subjects,
            partner_ids=partner_ids,
            email_layout_xmlid="mail.mail_notification_layout",
            model_description=model_description,
        )

    def _auto_subscribe_apply_parent_subtypes(
        self,
        subscriptions: list[tuple],
        subtype_maps: tuple,
        new_partner_subtypes: dict,
    ) -> None:
        child_ids, all_int_ids, parent = subtype_maps
        for partner_id, subtype_ids, pshare, active in subscriptions:
            if not (partner_id and active):
                continue
            sids = [parent[sid] for sid in subtype_ids if parent.get(sid)]
            sids += [
                sid for sid in subtype_ids if sid not in parent and sid in child_ids
            ]
            new_partner_subtypes[partner_id] = (
                set(sids) - set(all_int_ids) if pshare else set(sids)
            )

    def _auto_subscribe_apply_default_followers(
        self, updated_values: dict, def_ids: list[int], new_partner_subtypes: dict
    ) -> dict:
        notify_data = {}
        for partner_id, sids, template in self._message_auto_subscribe_followers(
            updated_values, def_ids
        ):
            new_partner_subtypes.setdefault(partner_id, sids)
            if template:
                partner = self.env["res.partner"].browse(partner_id)
                lang = partner.lang if partner else None
                notify_data.setdefault((template, lang), []).append(partner_id)
        return notify_data

    def _message_auto_subscribe(
        self, updated_values: dict, followers_existing_policy: str = "skip"
    ) -> bool:
        if not self:
            return True

        new_partner_subtypes = {}

        updated_relation = {}
        child_ids, def_ids, all_int_ids, parent, relation = self.env[
            "mail.message.subtype"
        ]._get_auto_subscription_subtypes(self._name)
        subtype_maps = (child_ids, all_int_ids, parent)

        for res_model, fnames in relation.items():
            for field in (fname for fname in fnames if updated_values.get(fname)):
                updated_relation.setdefault(res_model, set()).add(field)
        if updated_relation:
            doc_data = [
                (model, [updated_values[fname] for fname in fnames])
                for model, fnames in updated_relation.items()
            ]
            res = self.env["mail.followers"]._get_subscription_data(
                doc_data, None, include_partner=True
            )
            self._auto_subscribe_apply_parent_subtypes(
                [row[3:] for row in res], subtype_maps, new_partner_subtypes
            )

        notify_data = self._auto_subscribe_apply_default_followers(
            updated_values, def_ids, new_partner_subtypes
        )

        self.env["mail.followers"]._add_followers(
            self._name,
            self.ids,
            list(new_partner_subtypes),
            subtypes=new_partner_subtypes,
            check_existing=True,
            existing_policy=followers_existing_policy,
        )

        for (template, lang), pids in notify_data.items():
            self.with_context(lang=lang)._message_auto_subscribe_notify(pids, template)

        return True

    def _message_auto_subscribe_batch(
        self, vals_per_record: dict, followers_existing_policy: str = "skip"
    ) -> bool:
        if not self:
            return True

        child_ids, def_ids, all_int_ids, parent, relation = self.env[
            "mail.message.subtype"
        ]._get_auto_subscription_subtypes(self._name)
        subtype_maps = (child_ids, all_int_ids, parent)

        all_parent_ids_by_model = {}
        records_with_relations = {}

        for record_id, updated_values in vals_per_record.items():
            updated_relation = {}
            for res_model, fnames in relation.items():
                for fname in fnames:
                    if updated_values.get(fname):
                        updated_relation.setdefault(res_model, set()).add(fname)
                        all_parent_ids_by_model.setdefault(res_model, set()).add(
                            updated_values[fname]
                        )
            if updated_relation:
                records_with_relations[record_id] = (updated_values, updated_relation)

        parent_subscription_data = {}
        if all_parent_ids_by_model:
            res = self.env["mail.followers"]._get_subscription_data(
                [
                    (model, list(pids))
                    for model, pids in all_parent_ids_by_model.items()
                ],
                None,
                include_partner=True,
            )
            for (
                _fol_id,
                res_model,
                res_id,
                partner_id,
                subtype_ids,
                pshare,
                active,
            ) in res:
                parent_subscription_data.setdefault((res_model, res_id), []).append(
                    (partner_id, subtype_ids, pshare, active)
                )

        all_new_partner_subtypes = {}
        all_notify_data = {}

        for record in self:
            record_id = record.id
            updated_values = vals_per_record[record_id]
            new_partner_subtypes = {}

            if record_id in records_with_relations:
                _vals, rec_updated_relation = records_with_relations[record_id]
                for res_model, fnames in rec_updated_relation.items():
                    for fname in fnames:
                        parent_doc_id = updated_values[fname]
                        record._auto_subscribe_apply_parent_subtypes(
                            parent_subscription_data.get(
                                (res_model, parent_doc_id), []
                            ),
                            subtype_maps,
                            new_partner_subtypes,
                        )

            notify_data = record._auto_subscribe_apply_default_followers(
                updated_values, def_ids, new_partner_subtypes
            )

            if new_partner_subtypes:
                all_new_partner_subtypes[record_id] = new_partner_subtypes
            if notify_data:
                all_notify_data[record_id] = notify_data

        if all_new_partner_subtypes:
            self.env["mail.followers"]._add_followers_multi(
                self._name,
                all_new_partner_subtypes,
                check_existing=True,
                existing_policy=followers_existing_policy,
            )

        self._message_auto_subscribe_notify_batch(all_notify_data)

        return True

    def _message_auto_subscribe_notify_batch(
        self, notify_data_per_record: dict
    ) -> None:
        notify_groups = {}
        for record_id, notify_data in notify_data_per_record.items():
            for (template, lang), partner_ids in notify_data.items():
                notify_groups.setdefault(
                    (template, lang, tuple(sorted(partner_ids))), []
                ).append(record_id)
        for (template, lang, partner_ids), record_ids in notify_groups.items():
            self.browse(record_ids).with_context(
                lang=lang
            )._message_auto_subscribe_notify(list(partner_ids), template)

    @api.readonly
    def message_get_followers(
        self,
        after: int | None = None,
        limit: int | None = None,
        filter_recipients: bool = False,
    ) -> dict:
        self.ensure_one()
        store = Store()
        self._message_followers_to_store(
            store, after, limit or self._FOLLOWER_PAGE_LIMIT, filter_recipients
        )
        return store.get_result()

    def _message_followers_to_store(
        self,
        store: Store,
        after: int | None = None,
        limit: int | None = None,
        filter_recipients: bool = False,
        reset: bool = False,
    ) -> MailFollowers:
        self.ensure_one()
        limit = self._FOLLOWER_PAGE_LIMIT if limit is None else limit
        domain = Domain(
            [
                ("res_id", "=", self.id),
                ("res_model", "=", self._name),
                ("partner_id", "!=", self.env.user.partner_id.id),
            ]
        )
        if filter_recipients:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_comment")
            domain &= Domain(
                [
                    ("subtype_ids", "=", subtype_id),
                    ("partner_id.active", "=", True),
                ]
            )
        if after:
            domain &= Domain("id", ">", after)
        followers = self.env["mail.followers"].search(
            domain, limit=limit, order="id ASC"
        )
        store.add(
            self,
            {
                "recipients" if filter_recipients else "followers": Store.Many(
                    followers,
                    mode="ADD" if not reset else "REPLACE",
                ),
            },
            as_thread=True,
        )
        return followers

    def message_change_thread(
        self,
        new_thread: models.BaseModel,
        new_parent_message: MailMessage | Literal[False] = False,
    ) -> bool:
        self.ensure_one()
        self.check_access("write")
        new_thread.check_access("read")
        MailMessage = self.env["mail.message"]
        messages = MailMessage.search(
            [
                ("model", "=", self._name),
                ("res_id", "=", self.id),
                ("message_type", "!=", "user_notification"),
            ]
        )
        non_generic_messages = messages.filtered(lambda m: m.subtype_id.res_model)
        generic_messages = messages - non_generic_messages

        msg_vals = {"res_id": new_thread.id, "model": new_thread._name}
        if new_parent_message:
            msg_vals["parent_id"] = new_parent_message.id
        generic_messages.sudo().write(msg_vals)

        messages_with_description = MailMessage

        if self._name != new_thread._name:
            msg_vals["subtype_id"] = None

            messages_with_description = non_generic_messages.filtered(
                lambda msg: msg.subtype_id.description
            )
            for message in messages_with_description:
                body = append_content_to_html(
                    message.subtype_id.description,
                    message.body,
                )
                message.sudo().write({**msg_vals, "body": body})

        (non_generic_messages - messages_with_description).sudo().write(msg_vals)
        return True

    def _message_update_content(
        self,
        message: MailMessage,
        /,
        *,
        body: str,
        attachment_ids: list[int] | None = None,
        partner_ids: list[int] | None = None,
        strict: bool = True,
        **kwargs,
    ) -> None:
        self.ensure_one()
        if strict:
            self._check_can_update_message_content(message.sudo())

        msg_values = {}
        if body is False:
            body = ""
        if body is not None:
            if body or not message._filter_empty():
                tree = html.fragment_fromstring(_escape_body(body), create_parent="div")
                children = list(tree)
                if len(children) > 0:
                    last_div_element = (
                        children[-1] if children[-1].tag in ["div", "p"] else tree
                    )
                    last_div_element.text = (last_div_element.text or "") + (
                        " " if last_div_element.text else ""
                    )
                    etree.SubElement(
                        last_div_element,
                        "span",
                        attrib={"class": "o-mail-Message-edited"},
                    )
                    msg_values["body"] = (tree.text or "") + Markup(
                        "".join(
                            etree.tostring(child, encoding="unicode") for child in tree
                        )
                    )
                else:
                    msg_values["body"] = _escape_body(body) + Markup(
                        "<span class='o-mail-Message-edited'/>"
                    )
            else:
                msg_values["body"] = ""
        if attachment_ids:
            msg_values.update(
                self._process_attachments_for_post(
                    [],
                    attachment_ids,
                    {
                        "body": body,
                        "model": self._name,
                        "res_id": self.id,
                    },
                )
            )
        elif attachment_ids is not None:
            message.attachment_ids._delete_and_notify()
        if partner_ids is not None:
            msg_values.update(
                {"partner_ids": [int(pid) for pid in partner_ids] or False}
            )
        if "subject" in kwargs:
            msg_values["subject"] = kwargs["subject"]
        if msg_values:
            message.write(msg_values)
        if message._filter_empty():
            self._clean_empty_message(message)

        if "scheduled_date" in kwargs:
            if kwargs["scheduled_date"]:
                self.env[
                    "mail.message.schedule"
                ].sudo()._update_message_scheduled_datetime(
                    message, kwargs["scheduled_date"]
                )
            else:
                self.env["mail.message.schedule"].sudo()._send_message_notifications(
                    message
                )

        res = [
            Store.Many("attachment_ids", sort="id"),
            "body",
            Store.Many("partner_ids", ["avatar_128", "name"]),
            "pinned_at",
            "write_date",
            *message._get_store_linked_messages_fields(),
            *self._get_store_message_update_extra_fields(),
        ]
        if "subject" in kwargs:
            res.append("subject")
        if body is not None:
            self.env["mail.message.translation"].sudo().search(
                [("message_id", "=", message.id)]
            ).unlink()
            res.append({"translationValue": False})
        Store(bus_channel=message._bus_channel()).add(message, res).bus_send()

    def _clean_empty_message(self, message: MailMessage) -> None:
        message.message_link_preview_ids._unlink_and_notify()

    def _get_store_message_update_extra_fields(self) -> list[StoreFieldSpec]:
        return []

    def _thread_to_store(
        self,
        store: Store,
        fields: StoreFieldsInput,
        *,
        request_list: list[str] | None = None,
    ) -> None:
        is_request = request_list is not None
        request_list = request_list or []
        store.add_records_fields(self, fields, as_thread=True)
        is_own_target = is_request and store.target.is_current_user(self.env)
        post_operations = (
            self._mail_get_operation_for_mail_message_operation("create")
            if is_own_target
            else {}
        )
        is_activity_mixin = isinstance(
            self.env[self._name], self.env.registry["mail.activity.mixin"]
        )
        readable = writable = self.browse()
        if is_own_target:
            readable = self.sudo(False)._filtered_access("read")
            writable = self.sudo(False)._filtered_access("write")
        self_follower_by_res_id = {}
        if "followers" in request_list:
            for follower in self.env["mail.followers"].search(
                [
                    ("res_id", "in", self.ids),
                    ("res_model", "=", self._name),
                    ("partner_id", "=", self.env.user.partner_id.id),
                ]
            ):
                self_follower_by_res_id[follower.res_id] = follower
        scheduled_by_res_id = defaultdict(lambda: self.env["mail.scheduled.message"])
        if "scheduledMessages" in request_list:
            for scheduled in self.env["mail.scheduled.message"].search(
                [("model", "=", self._name), ("res_id", "in", self.ids)]
            ):
                scheduled_by_res_id[scheduled.res_id] |= scheduled
        for thread in self:
            res = {}
            if is_own_target:
                res["hasReadAccess"] = thread in readable
                res["hasWriteAccess"] = thread in writable
                res["canPostOnReadonly"] = post_operations.get(thread) == "read"
            if "activities" in request_list and is_activity_mixin:
                res["activities"] = Store.Many(
                    thread.with_context(active_test=True).activity_ids
                )
            if "attachments" in request_list:
                res["attachments"] = Store.Many(
                    thread._get_mail_thread_data_attachments()
                )
                res["areAttachmentsLoaded"] = True
                res["isLoadingAttachments"] = False
            if "contact_fields" in request_list:
                res["primary_email_field"] = thread._mail_get_primary_email_field()
                res["partner_fields"] = thread._mail_get_partner_fields()
            if "followers" in request_list:
                limit = self._FOLLOWER_PAGE_LIMIT
                self_follower = self_follower_by_res_id.get(
                    thread.id, self.env["mail.followers"]
                )
                res["selfFollower"] = Store.One(self_follower)
                followers = thread._message_followers_to_store(
                    store, limit=limit, reset=True
                )
                if len(followers) < limit:
                    res["followersCount"] = len(followers) + (1 if self_follower else 0)
                else:
                    res["followersCount"] = self.env["mail.followers"].search_count(
                        [("res_id", "=", thread.id), ("res_model", "=", self._name)]
                    )
                recipients = thread._message_followers_to_store(
                    store, limit=limit, filter_recipients=True, reset=True
                )
                if len(recipients) < limit:
                    res["recipientsCount"] = len(recipients)
                else:
                    subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_comment"
                    )
                    res["recipientsCount"] = self.env["mail.followers"].search_count(
                        [
                            ("res_id", "=", thread.id),
                            ("res_model", "=", self._name),
                            ("partner_id", "!=", self.env.user.partner_id.id),
                            ("subtype_ids", "=", subtype_id),
                            ("partner_id.active", "=", True),
                        ]
                    )
            if "display_name" in request_list:
                res["display_name"] = thread.display_name
            if "scheduledMessages" in request_list:
                res["scheduledMessages"] = Store.Many(scheduled_by_res_id[thread.id])
            if "suggestedRecipients" in request_list:
                res["suggestedRecipients"] = thread._message_get_suggested_recipients(
                    reply_discussion=True,
                    no_create=True,
                )
            if res:
                store.add(thread, res, as_thread=True)

    def _get_mail_thread_data_attachments(self) -> IrAttachment:
        self.ensure_one()
        res = self.env["ir.attachment"].search(
            [("res_id", "=", self.id), ("res_model", "=", self._name)], order="id desc"
        )
        if "original_id" in self.env["ir.attachment"]._fields:
            svg_ids = res.filtered(
                lambda attachment: attachment.mimetype == "image/svg+xml"
            )
            non_svg_ids = res - svg_ids
            original_ids = res.mapped("original_id")
            svg_id_set = set(svg_ids._ids)
            non_svg_id_set = set(non_svg_ids._ids)
            original_id_set = set(original_ids._ids)
            res = res.filtered(
                lambda attachment: (
                    (
                        attachment.id in svg_id_set
                        and attachment.id not in original_id_set
                    )
                    or (
                        attachment.id in non_svg_id_set
                        and attachment.original_id.id not in non_svg_id_set
                    )
                )
            )
        return res

    def _get_allowed_message_params(self) -> set:
        return {"email_add_signature", "message_type", "subject", "subtype_xmlid"}

    @api.model
    def _get_allowed_access_params(self) -> set:
        return set()

    @api.model
    def _get_thread_with_access(
        self, thread_id: int, *, mode: str = "read", **kwargs
    ) -> Self:
        allowed_params = self._get_allowed_access_params()
        if invalid := (set((kwargs or {}).keys()) - allowed_params):
            _logger.warning(
                "Invalid access parameters to _get_thread_with_access: %s", invalid
            )

        thread = self.browse(thread_id)
        if thread.exists() and thread.sudo(False).with_context(
            allowed_company_ids=[]
        ).has_access(mode):
            return thread
        return self.browse()
