import typing
from datetime import datetime
from typing import Any, Literal

from markupsafe import Markup
from werkzeug.exceptions import NotFound

from odoo import http, models
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.mail import email_normalize
from odoo.tools.misc import verify_limited_field_access_token

from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

if typing.TYPE_CHECKING:
    from odoo.addons.mail.models.mail_message import MailMessage
    from odoo.addons.mail.models.res_partner import ResPartner


def _to_record_id(value: Any) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        raise NotFound from None


def _to_record_ids_strict(values: list | None) -> list:
    return [_to_record_id(value) for value in values or []]


def _to_record_ids(values: list | None, limit: int | None = None) -> list:
    result = []
    for value in values or []:
        try:
            result.append(int(value))
        except TypeError, ValueError:
            continue
        if limit is not None and len(result) >= limit:
            break
    return result


def _to_thread_model(model_name: str) -> models.Model:
    if model_name not in request.env:
        raise NotFound
    model = request.env[model_name]
    if not isinstance(model, request.env.registry["mail.thread"]):
        raise NotFound
    return model


class ThreadController(http.Controller):
    @classmethod
    def _get_message_with_access(
        cls, message_id: int, mode: str = "read", **kwargs
    ) -> models.Model:
        message_su = (
            request.env["mail.message"]
            .sudo()
            .browse(_to_record_id(message_id))
            .exists()
        )
        if not message_su:
            return message_su
        allowed_params = message_su._get_thread_model()._get_allowed_access_params()
        return request.env["mail.message"]._get_with_access(
            message_su.id,
            mode=mode,
            **{key: value for key, value in kwargs.items() if key in allowed_params},
        )

    @classmethod
    def _get_thread_with_access_for_post(
        cls, thread_model: str, thread_id: int, **kwargs
    ) -> models.Model:
        thread_su = (
            _to_thread_model(thread_model).sudo().browse(_to_record_id(thread_id))
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
        return model._get_thread_with_access(
            _to_record_id(thread_id),
            mode=mode,
            **{
                key: value
                for key, value in kwargs.items()
                if key in model._get_allowed_access_params()
            },
        )

    @http.route("/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_messages(
        self, thread_model: str, thread_id: int, fetch_params: dict | None = None
    ) -> dict:
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        res = request.env["mail.message"]._message_fetch(
            domain=None,
            thread=thread,
            **request.env["mail.message"]._sanitize_fetch_params(fetch_params),
        )
        messages = res.pop("messages")
        if not request.env.user._is_public():
            messages.set_message_done()
        return {
            **res,
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }

    @http.route(
        "/mail/thread/recipients", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_recipients(
        self, thread_model: str, thread_id: int, message_id: int | None = None
    ) -> list:
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        no_create = not thread.has_access("write")
        if message_id:
            message = self._get_message_with_access(message_id, mode="read")
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
            {"id": info["partner_id"], "email": info["email"], "name": info["name"]}
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
        partner_ids = request.env["res.partner"].search([("id", "in", partner_ids)])
        recipients = thread._message_get_suggested_recipients(
            reply_discussion=True,
            additional_partners=partner_ids,
            primary_email=main_email,
        )
        if partner_ids:
            old_customer_ids = set(thread._mail_get_partners()[thread.id].ids) - set(
                partner_ids.ids
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
        thread = _to_thread_model(thread_model)
        record_id = _to_record_id(thread_id)
        if record_id:
            thread = thread._get_thread_with_access(record_id, mode="read") or thread
        partners = thread._partner_find_from_emails_single(
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
        follower = request.env["mail.followers"].browse(_to_record_id(follower_id))
        follower.check_access("read")
        if follower.res_model not in request.env:
            raise NotFound
        record = request.env[follower.res_model].browse(follower.res_id)
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

    def _is_mentionable_in_thread(
        self, partner: ResPartner, thread: models.Model
    ) -> bool:
        if thread._name != "discuss.channel":
            return True
        channel_sudo = thread.sudo()
        channels = channel_sudo.parent_channel_id | channel_sudo
        return partner in channels.channel_member_ids.partner_id

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
                _to_record_ids_strict(attachment_ids)
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
            res["body"] = (
                Markup(post_data["body"]) if post_data["body"] else post_data["body"]
            )
        partner_ids = post_data.get("partner_ids")
        partner_emails = post_data.get("partner_emails")
        role_ids = post_data.get("role_ids")
        if (
            partner_ids is not None
            or partner_emails is not None
            or role_ids is not None
        ):
            partners = request.env["res.partner"].browse(
                _to_record_ids_strict(partner_ids)
            )
            if partner_emails:
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
                        [("role_ids", "in", _to_record_ids_strict(role_ids))],
                        ["partner_id"],
                    )
                    .partner_id
                )
            res["partner_ids"] = partners.filtered(
                lambda p: (
                    (not request.env.user.share and p.has_access("read"))
                    or (
                        verify_limited_field_access_token(
                            p,
                            "id",
                            post_data.get("partner_ids_mention_token", {}).get(
                                str(p.id), ""
                            ),
                            scope="mail.message_mention",
                        )
                        and self._is_mentionable_in_thread(p, thread)
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
        if context:
            request.update_context(**context)
        canned_response_ids = tuple(
            cid for cid in kwargs.get("canned_response_ids", []) if isinstance(cid, int)
        )
        if canned_response_ids:
            request.env.cr.execute(
                """
                UPDATE mail_canned_response SET last_used=%(last_used)s
                WHERE id IN (
                    SELECT id from mail_canned_response WHERE id = ANY(%(ids)s)
                    FOR NO KEY UPDATE SKIP LOCKED
                )
            """,
                {
                    "last_used": datetime.now(),
                    "ids": list(canned_response_ids),
                },
            )
        thread = self._get_thread_with_access_for_post(
            thread_model, thread_id, **kwargs
        )
        if not thread:
            raise NotFound
        if not self._get_thread_with_access(thread_model, thread_id, mode="write"):
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
        thread = request.env[message.model].browse(message.res_id)
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

    @http.route(
        "/mail/thread/unsubscribe", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_unsubscribe(
        self, res_model: str, res_id: int, partner_ids: list[int]
    ) -> dict:
        thread = _to_thread_model(res_model).browse(_to_record_id(res_id))
        thread.message_unsubscribe(_to_record_ids(partner_ids))
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

    @http.route("/mail/thread/subscribe", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_subscribe(
        self, res_model: str, res_id: int, partner_ids: list[int]
    ) -> dict:
        thread = _to_thread_model(res_model).browse(_to_record_id(res_id))
        thread.message_subscribe(_to_record_ids(partner_ids))
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
