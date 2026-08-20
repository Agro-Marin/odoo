import logging
import typing
from typing import Any, Literal

from markupsafe import Markup
from werkzeug.exceptions import NotFound

from odoo import http, models
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.mail import email_normalize
from odoo.tools.misc import verify_limited_field_access_token

from odoo.addons.mail.controllers.utils import (
    message_fetch_response,
    to_record_id,
    to_record_ids,
)
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

_logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from odoo.addons.mail.models.mail_message import MailMessage

MAX_EMAILS_PER_REQUEST = 50


def _to_thread_model(model_name: Any) -> models.Model:
    if not isinstance(model_name, str):
        raise NotFound
    if model_name not in request.env:
        raise NotFound
    model = request.env[model_name]
    if not isinstance(model, request.env.registry["mixin.mail.thread"]):
        raise NotFound
    return model


class ThreadController(http.Controller):
    CLIENT_CONTEXT_KEYS = frozenset(
        {
            "active_test",
            "allowed_company_ids",
            "lang",
            "temporary_id",
            "tz",
            "uid",
        }
    )

    @classmethod
    def _update_context_from_client(cls, context: dict | None) -> None:
        if not context:
            return
        if not isinstance(context, dict):
            raise NotFound
        allowed = cls.CLIENT_CONTEXT_KEYS
        if dropped := set(context) - allowed:
            _logger.debug("Ignoring context keys from the client: %s", sorted(dropped))
        request.update_context(
            **{key: value for key, value in context.items() if key in allowed}
        )

    @classmethod
    def _get_message_with_access(
        cls, message_id: int, mode: str = "read", **kwargs
    ) -> models.Model:
        return request.env["mail.message"]._get_with_access(
            to_record_id(message_id), mode=mode, **kwargs
        )

    @classmethod
    def _get_thread_with_access_for_post(
        cls, thread_model: str, thread_id: int, **kwargs
    ) -> models.Model:
        thread_su = (
            _to_thread_model(thread_model).sudo().browse(to_record_id(thread_id))
        )
        access_mode = thread_su._mail_get_operation_for_mail_message_operation(
            "create"
        ).get(thread_su)
        if not access_mode:
            return request.env[thread_model]
        return cls._get_thread_with_access(
            thread_model, thread_id, mode=access_mode, **kwargs
        )

    @classmethod
    def _get_thread_with_access(
        cls, thread_model: str, thread_id: int, mode: str = "read", **kwargs
    ) -> models.Model:
        model = _to_thread_model(thread_model)
        allowed_params = model._get_allowed_access_params()
        return model._get_thread_with_access(
            to_record_id(thread_id),
            mode=mode,
            **{key: value for key, value in kwargs.items() if key in allowed_params},
        )

    @classmethod
    def _has_post_write_access(cls, thread: models.Model) -> bool:
        return (
            thread.sudo(False).with_context(allowed_company_ids=[]).has_access("write")
        )

    @http.route("/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_messages(
        self, thread_model: str, thread_id: int, fetch_params: dict | None = None
    ) -> dict:
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        if not thread:
            raise NotFound
        return message_fetch_response(
            thread=thread, fetch_params=fetch_params, mark_done=True
        )

    @http.route(
        "/mail/thread/recipients", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_recipients(
        self, thread_model: str, thread_id: int, message_id: int | None = None
    ) -> list:
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        if not thread:
            raise NotFound
        no_create = not request.env.user.has_group("base.group_partner_manager")
        if message_id:
            message = self._get_message_with_access(message_id, mode="read")
            if not message or (message.sudo().model, message.sudo().res_id) != (
                thread._name,
                thread.id,
            ):
                raise NotFound
            suggested = thread._message_get_suggested_recipients(
                reply_message=message,
                no_create=no_create,
            )
        else:
            suggested = thread._message_get_suggested_recipients(
                reply_discussion=True,
                no_create=no_create,
            )
        return [
            {
                "partner_id": info["partner_id"],
                "email": info["email"],
                "name": info["name"],
            }
            for info in suggested
            if info["partner_id"]
        ]

    @http.route(
        "/mail/thread/recipients/get_suggested_recipients",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
    )
    def mail_thread_recipients_get_suggested_recipients(
        self,
        thread_model: str,
        thread_id: int,
        partner_ids: list[int] | None = None,
        main_email: str | Literal[False] = False,
    ) -> list:
        thread = self._get_thread_with_access(thread_model, thread_id)
        if not thread:
            raise NotFound
        partners = request.env["res.partner"].search(
            [("id", "in", to_record_ids(partner_ids))]
        )
        recipients = thread._message_get_suggested_recipients(
            reply_discussion=True,
            additional_partners=partners,
            primary_email=main_email,
        )
        if partners:
            old_customer_ids = set(thread._mail_get_partners()[thread.id].ids) - set(
                partners.ids
            )
            recipients = list(
                filter(
                    lambda rec: rec.get("partner_id") not in old_customer_ids,
                    recipients,
                )
            )
        return [
            {
                key: recipient[key]
                for key in recipient
                if key in ["name", "email", "partner_id"]
            }
            for recipient in recipients
        ]

    @http.route(
        "/mail/partner/from_email", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_partner_from_email(
        self, thread_model: str, thread_id: int, emails: list[str]
    ) -> list:
        if isinstance(emails, str) or not isinstance(emails, (list, tuple)):
            raise NotFound
        if len(emails) > MAX_EMAILS_PER_REQUEST:
            raise NotFound
        model = _to_thread_model(thread_model)
        record_id = to_record_id(thread_id)
        thread = model._get_thread_with_access(record_id, mode="read")
        if record_id and not thread:
            raise NotFound
        partners = (thread or model)._partner_find_from_emails_single(
            emails,
            no_create=not request.env.user.has_group("base.group_partner_manager"),
        )
        source_by_normalized = {}
        for email in emails:
            source_by_normalized.setdefault(
                email_normalize(email, strict=False) or email, email
            )
        return [
            {
                "id": partner.id,
                "name": partner.name,
                "email": partner.email,
                "source_email": source_by_normalized.get(
                    email_normalize(partner.email, strict=False) or partner.email
                ),
            }
            for partner in partners
        ]

    @http.route(
        "/mail/read_subscription_data", methods=["POST"], type="jsonrpc", auth="user"
    )
    def read_subscription_data(self, follower_id: int) -> dict:
        follower = request.env["mail.followers"].browse(to_record_id(follower_id))
        if not follower.exists():
            raise NotFound
        follower.check_access("read")
        if follower.res_model not in request.env:
            raise NotFound
        record = request.env[follower.res_model].browse(follower.res_id)
        if not record.exists():
            raise NotFound
        record.check_access("read")
        subtypes = record._mail_get_message_subtypes()
        store = Store().add(subtypes, ["name"]).add(follower, ["subtype_ids"])
        return {
            "store_data": store.get_result(),
            "subtype_ids": subtypes.sorted(
                key=lambda s: (
                    s.parent_id.res_model or "",
                    s.res_model or "",
                    s.internal,
                    s.sequence,
                ),
            ).ids,
        }

    def _mentionable_partner_ids(self, thread: models.Model) -> set[int] | None:
        if thread._name != "discuss.channel":
            return None
        channel_sudo = thread.sudo()
        channels = channel_sudo.parent_channel_id | channel_sudo
        return set(channels.channel_member_ids.partner_id.ids)

    def _prepare_message_data(
        self,
        post_data: dict,
        *,
        thread: models.Model,
        from_create: bool = True,
        **kwargs,
    ) -> dict:
        res = {
            key: value
            for key, value in post_data.items()
            if key in thread._get_allowed_message_params()
        }
        if (attachment_ids := post_data.get("attachment_ids")) is not None:
            attachments = request.env["ir.attachment"].browse(
                to_record_ids(attachment_ids)
            )
            if not attachments._has_attachments_ownership(
                post_data.get("attachment_tokens")
            ):
                msg = request.env._(
                    "One or more attachments do not exist, or you do not have the rights to access them.",
                )
                raise UserError(msg)
            res["attachment_ids"] = attachments.ids
        if "body" in post_data:
            body = post_data["body"]
            if body and not isinstance(body, str):
                raise NotFound
            res["body"] = Markup(body) if body else body
        partner_ids = post_data.get("partner_ids")
        partner_emails = post_data.get("partner_emails")
        role_ids = post_data.get("role_ids")
        if (
            partner_ids is not None
            or partner_emails is not None
            or role_ids is not None
        ):
            partners = request.env["res.partner"].browse(to_record_ids(partner_ids))
            if partner_emails:
                if isinstance(partner_emails, str) or not isinstance(
                    partner_emails, (list, tuple)
                ):
                    raise NotFound
                if len(partner_emails) > MAX_EMAILS_PER_REQUEST:
                    raise NotFound
                partners |= thread._partner_find_from_emails_single(
                    partner_emails,
                    no_create=not request.env.user.has_group(
                        "base.group_partner_manager"
                    ),
                )
            if role_ids:
                partners |= (
                    request.env["res.users"]
                    .sudo()
                    .search_fetch(
                        [("role_ids", "in", to_record_ids(role_ids))],
                        ["partner_id"],
                    )
                    .partner_id
                )
            readable_ids = (
                set(partners._filtered_access("read").ids)
                if not request.env.user.share
                else set()
            )
            mention_tokens = post_data.get("partner_ids_mention_token") or {}
            mentionable_ids = self._mentionable_partner_ids(thread)
            res["partner_ids"] = partners.filtered(
                lambda p: (
                    p.id in readable_ids
                    or (
                        verify_limited_field_access_token(
                            p,
                            "id",
                            mention_tokens.get(str(p.id), ""),
                            scope="mail.message_mention",
                        )
                        and (mentionable_ids is None or p.id in mentionable_ids)
                    )
                ),
            ).ids
        if from_create:
            res.setdefault("message_type", "comment")
        return res

    @http.route("/mail/message/post", methods=["POST"], type="jsonrpc", auth="public")
    @add_guest_to_context
    def mail_message_post(
        self,
        thread_model: str,
        thread_id: int,
        post_data: dict,
        context: dict | None = None,
        **kwargs,
    ) -> dict:
        store = Store()
        request.update_context(message_post_store=store)
        self._update_context_from_client(context)
        request.env["mail.canned.response"]._register_usage(
            kwargs.get("canned_response_ids")
        )
        thread = self._get_thread_with_access_for_post(
            thread_model, thread_id, **kwargs
        )
        if not thread:
            raise NotFound
        if not self._has_post_write_access(thread):
            thread = thread.with_context(
                mail_post_autofollow_author_skip=True, mail_post_autofollow=False
            )
        message = thread.sudo().message_post(
            **self._prepare_message_data(
                post_data, thread=thread, from_create=True, **kwargs
            ),
        )
        return {
            "store_data": store.add(message).get_result(),
            "message_id": message.id,
        }

    @http.route(
        "/mail/message/update_content", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def mail_message_update_content(
        self, message_id: int, update_data: dict, **kwargs
    ) -> dict:
        message = self._get_message_with_access(message_id, mode="create", **kwargs)
        if not message or not self._can_edit_message(message, **kwargs):
            raise NotFound
        message = message.sudo()
        thread = _to_thread_model(message.model).browse(message.res_id)
        thread._message_update_content(
            message,
            **self._prepare_message_data(
                update_data, thread=thread, from_create=False, **kwargs
            ),
        )
        return Store().add(message).get_result()

    @classmethod
    def _can_edit_message(cls, message: MailMessage, **kwargs) -> bool:
        return (
            message.sudo().is_current_user_or_guest_author
            or request.env.user._is_admin()
        )

    def _follower_change_response(
        self, res_model: str, res_id: int, partner_ids: list[int], *, subscribe: bool
    ) -> dict:
        thread = _to_thread_model(res_model).browse(to_record_id(res_id)).exists()
        if not thread:
            raise NotFound
        partner_ids = to_record_ids(partner_ids)
        if subscribe:
            thread.message_subscribe(partner_ids)
        else:
            thread.message_unsubscribe(partner_ids)
        return (
            Store()
            .add(
                thread,
                [],
                as_thread=True,
                request_list=["followers", "suggestedRecipients"],
            )
            .get_result()
        )

    @http.route(
        "/mail/thread/unsubscribe", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_unsubscribe(
        self, res_model: str, res_id: int, partner_ids: list[int]
    ) -> dict:
        return self._follower_change_response(
            res_model, res_id, partner_ids, subscribe=False
        )

    @http.route("/mail/thread/subscribe", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_subscribe(
        self, res_model: str, res_id: int, partner_ids: list[int]
    ) -> dict:
        return self._follower_change_response(
            res_model, res_id, partner_ids, subscribe=True
        )
