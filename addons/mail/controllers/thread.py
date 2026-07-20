from datetime import datetime

from markupsafe import Markup
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.mail import email_normalize
from odoo.tools.misc import verify_limited_field_access_token

from odoo.addons.mail.tools.discuss import Store, add_guest_to_context


def _to_record_id(value):
    """Coerce a client-supplied record id to ``int``, or raise ``NotFound``.

    These chatter routes are ``auth="public"`` with fully client-controlled
    ids. A non-numeric id used to reach ``int()`` / ``browse()`` and surface an
    uncaught ``ValueError`` as an "Odoo Server Error" (leaking a traceback and
    model internals to anonymous callers). A 404 is the correct answer: the id
    namespace simply does not contain that value.
    """
    try:
        return int(value)
    except TypeError, ValueError:
        raise NotFound from None


def _to_record_ids(values, limit=None):
    """Coerce a client-supplied list of record ids to a list of ``int``.

    Non-integer entries are dropped rather than surfacing an uncaught
    ``ValueError`` (same rationale as ``_to_record_id``). When ``limit`` is set,
    at most that many ids are kept, bounding the size of the resulting domain on
    ``auth="public"`` routes.
    """
    result = []
    for value in values or []:
        try:
            result.append(int(value))
        except TypeError, ValueError:
            continue
        if limit is not None and len(result) >= limit:
            break
    return result


class ThreadController(http.Controller):
    # access helpers
    # ------------------------------------------------------------

    @classmethod
    def _get_message_with_access(cls, message_id, mode="read", **kwargs):
        """Simplified getter that filters access params only, making model methods
        using strong parameters."""
        message_su = (
            request.env["mail.message"]
            .sudo()
            .browse(_to_record_id(message_id))
            .exists()
        )
        if not message_su:
            return message_su
        return request.env["mail.message"]._get_with_access(
            message_su.id,
            mode=mode,
            **{
                key: value
                for key, value in kwargs.items()
                if key
                in request.env[
                    message_su.model or "mail.thread"
                ]._get_allowed_access_params()
            },
        )

    @classmethod
    def _get_thread_with_access_for_post(cls, thread_model, thread_id, **kwargs):
        """Helper allowing to fetch thread with access when requesting 'create'
        access on mail.message, aka rights to post on the document. Default
        behavior is to rely on _mail_post_access but it might be customized.
        See '_mail_get_operation_for_mail_message_operation'."""
        if thread_model not in request.env:
            raise NotFound
        thread_su = request.env[thread_model].sudo().browse(_to_record_id(thread_id))
        access_mode = thread_su._mail_get_operation_for_mail_message_operation(
            "create"
        )[thread_su]
        if not access_mode:
            return request.env[
                thread_model
            ]  # match _get_thread_with_access void result
        return cls._get_thread_with_access(
            thread_model, thread_id, mode=access_mode, **kwargs
        )

    @classmethod
    def _get_thread_with_access(cls, thread_model, thread_id, mode="read", **kwargs):
        """Simplified getter that filters access params only, making model methods
        using strong parameters."""
        if thread_model not in request.env:
            raise NotFound
        return request.env[thread_model]._get_thread_with_access(
            _to_record_id(thread_id),
            mode=mode,
            **{
                key: value
                for key, value in kwargs.items()
                if key in request.env[thread_model]._get_allowed_access_params()
            },
        )

    # main routes
    # ------------------------------------------------------------

    @http.route("/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_messages(self, thread_model, thread_id, fetch_params=None):
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        res = request.env["mail.message"]._message_fetch(
            domain=None, thread=thread, **(fetch_params or {})
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
    def mail_thread_recipients(self, thread_model, thread_id, message_id=None):
        """Fetch discussion-based suggested recipients, creating partners on the fly
        only when the caller can write the record."""
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        # Only auto-create res.partner rows from the record's email fields when the
        # caller can actually write the record. This route only needs read access,
        # so a read-only viewer must not be able to spawn partners as a side effect
        # of merely fetching suggestions.
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
        "/mail/thread/recipients/fields", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_recipients_fields(self, thread_model):
        # Guard the caller-supplied model name like the sibling routes do:
        # otherwise ``request.env[thread_model]`` raises KeyError -> HTTP 500
        # (log spam) on any bogus model instead of a clean 404.
        if thread_model not in request.env:
            raise NotFound
        return {
            "partner_fields": request.env[thread_model]._mail_get_partner_fields(),
            "primary_email_field": [
                request.env[thread_model]._mail_get_primary_email_field()
            ],
        }

    @http.route(
        "/mail/thread/recipients/get_suggested_recipients",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
    )
    def mail_thread_recipients_get_suggested_recipients(
        self, thread_model, thread_id, partner_ids=None, main_email=False
    ):
        """This method returns the suggested recipients with updates coming from the frontend.
        :param thread_model: Model on which we are currently working on.
        :param thread_id: ID of the document we need to compute
        :param partner_ids: IDs of new customers that were edited on the frontend, usually only the customer but could be more.
        :param main_email: New email edited on the frontend linked to the @see _mail_get_primary_email_field
        """
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
    def mail_thread_partner_from_email(self, thread_model, thread_id, emails):
        # thread_model / thread_id are fully client-controlled. Validate the
        # model (an unknown name used to KeyError -> 500) and bind to the record
        # only when the caller can actually read it: an inaccessible record falls
        # back to the generic (record-less) partner lookup — which
        # _partner_find_from_emails_single explicitly supports on a void
        # recordset — instead of deriving company/context from a thread the user
        # cannot access.
        if thread_model not in request.env:
            raise NotFound
        thread = request.env[thread_model]
        record_id = _to_record_id(thread_id)
        if record_id:
            thread = thread._get_thread_with_access(record_id, mode="read") or thread
        partners = thread._partner_find_from_emails_single(
            emails,
            no_create=not request.env.user.has_group("base.group_partner_manager"),
        )
        # The returned recordset is deduped and id-ordered, so a client cannot
        # positionally pair it with the input ``emails``. Echo the input email
        # that produced each partner (matched on normalized address) as
        # ``source_email`` so the client can associate results reliably.
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
    def read_subscription_data(self, follower_id):
        """Return the document's message subtypes and which of them are followed."""
        # limited to internal, who can read all followers
        follower = request.env["mail.followers"].browse(follower_id)
        follower.check_access("read")
        record = request.env[follower.res_model].browse(follower.res_id)
        record.check_access("read")
        # find current model subtypes, add them to a dictionary
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

    def _prepare_message_data(self, post_data, *, thread, **kwargs):
        res = {
            key: value
            for key, value in post_data.items()
            if key in thread._get_allowed_message_params()
        }
        if (attachment_ids := post_data.get("attachment_ids")) is not None:
            attachments = request.env["ir.attachment"].browse(map(int, attachment_ids))
            if not attachments._has_attachments_ownership(
                post_data.get("attachment_tokens")
            ):
                msg = request.env._(
                    "One or more attachments do not exist, or you do not have the rights to access them.",
                )
                raise UserError(msg)
            res["attachment_ids"] = attachments.ids
        if "body" in post_data:
            # User input is HTML string, so it needs to be in a Markup.
            # It will be sanitized by the field itself when writing on it.
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
            partners = request.env["res.partner"].browse(map(int, partner_ids or []))
            if partner_emails:
                partners |= thread._partner_find_from_emails_single(
                    partner_emails,
                    no_create=not request.env.user.has_group(
                        "base.group_partner_manager"
                    ),
                )
            if role_ids:
                # sudo - res.users: getting partners linked to the role is allowed.
                partners |= (
                    request.env["res.users"]
                    .sudo()
                    .search_fetch([("role_ids", "in", role_ids)], ["partner_id"])
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
                    )
                ),
            ).ids
        res.setdefault("message_type", "comment")
        return res

    @http.route("/mail/message/post", methods=["POST"], type="jsonrpc", auth="public")
    @add_guest_to_context
    def mail_message_post(
        self, thread_model, thread_id, post_data, context=None, **kwargs
    ):
        store = Store()
        request.update_context(message_post_store=store)
        if context:
            request.update_context(**context)
        canned_response_ids = tuple(
            cid for cid in kwargs.get("canned_response_ids", []) if isinstance(cid, int)
        )
        if canned_response_ids:
            # Avoid serialization errors since last used update is not
            # essential and should not block message post.
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
        # sudo: mail.thread - users can post on accessible threads
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
    def mail_message_update_content(self, message_id, update_data, **kwargs):
        message = self._get_message_with_access(message_id, mode="create", **kwargs)
        if not message or not self._can_edit_message(message, **kwargs):
            raise NotFound
        # sudo: mail.message - access is checked in _get_with_access and _can_edit_message
        message = message.sudo()
        thread = request.env[message.model].browse(message.res_id)
        thread._message_update_content(
            message,
            **self._prepare_message_data(
                update_data, thread=thread, from_create=False, **kwargs
            ),
        )
        return Store().add(message).get_result()

    # side check for access
    # ------------------------------------------------------------

    @classmethod
    def _can_edit_message(cls, message, **kwargs):
        return (
            message.sudo().is_current_user_or_guest_author
            or request.env.user._is_admin()
        )

    @http.route(
        "/mail/thread/unsubscribe", methods=["POST"], type="jsonrpc", auth="user"
    )
    def mail_thread_unsubscribe(self, res_model, res_id, partner_ids):
        if res_model not in request.env:
            raise NotFound
        thread = request.env[res_model].browse(_to_record_id(res_id))
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
    def mail_thread_subscribe(self, res_model, res_id, partner_ids):
        if res_model not in request.env:
            raise NotFound
        thread = request.env[res_model].browse(_to_record_id(res_id))
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
