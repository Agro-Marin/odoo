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

    404 is the correct answer for a non-numeric id: the id namespace does not
    contain that value, and letting it reach ``browse()`` surfaces a traceback
    as a 500 (to anonymous callers on the ``auth="public"`` chatter routes).
    """
    try:
        return int(value)
    except TypeError, ValueError:
        raise NotFound from None


def _to_record_ids_strict(values):
    """Coerce a client-supplied list of record ids to ``int``, or raise ``NotFound``.

    Unlike ``_to_record_ids`` this never drops an entry. Use it wherever the
    position of an id carries meaning: ``attachment_ids`` is zipped
    ``strict=True`` against ``attachment_tokens`` in
    ``ir.attachment._has_attachments_ownership``, so skipping a malformed id
    would slide every later attachment onto its neighbour's ownership token.
    """
    return [_to_record_id(value) for value in values or []]


def _to_record_ids(values, limit=None):
    """Coerce a client-supplied list of record ids to a list of ``int``.

    Non-integer entries are dropped rather than surfacing an uncaught
    ``ValueError`` (same rationale as ``_to_record_id``).

    :param limit: keep at most that many ids, bounding the resulting domain
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


def _to_thread_model(model_name):
    """Resolve a client-supplied model name to an empty thread recordset.

    ``mail.message._is_thread_model`` already established that registry
    membership is the wrong question on these routes: it rules out the
    uninstalled model (``KeyError``) but not the *installed non-thread* one, and
    every ``mail.thread`` method the chatter then calls on it -- here
    ``_get_allowed_access_params`` and ``_get_thread_with_access`` -- is an
    ``AttributeError``, i.e. an HTTP 500 naming the model back to the caller.
    404 is the right answer: the thread namespace does not contain that model.
    """
    if model_name not in request.env:
        raise NotFound
    model = request.env[model_name]
    if not isinstance(model, request.env.registry["mail.thread"]):
        raise NotFound
    return model


class ThreadController(http.Controller):
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
        # 'mail.message.model' is a free-form Char: fall back to the generic
        # mixin when it does not name a usable thread model, like
        # mail.message._get_with_access does for the very same lookup.
        # ``_get_thread_model`` covers both the uninstalled model and the live
        # non-thread one -- the latter reached this line as
        # ``AttributeError: 'res.currency' object has no attribute
        # '_get_allowed_access_params'``, an anonymous HTTP 500.
        allowed_params = message_su._get_thread_model()._get_allowed_access_params()
        return request.env["mail.message"]._get_with_access(
            message_su.id,
            mode=mode,
            **{key: value for key, value in kwargs.items() if key in allowed_params},
        )

    @classmethod
    def _get_thread_with_access_for_post(cls, thread_model, thread_id, **kwargs):
        """Helper allowing to fetch thread with access when requesting 'create'
        access on mail.message, aka rights to post on the document. Default
        behavior is to rely on _mail_post_access but it might be customized.
        See '_mail_get_operation_for_mail_message_operation'."""
        thread_su = (
            _to_thread_model(thread_model).sudo().browse(_to_record_id(thread_id))
        )
        # ``.get``: an override is allowed to grant no permission at all by
        # omitting the record, which must read as "denied" (the ``if not
        # access_mode`` below) and not raise a KeyError out of an HTTP route.
        access_mode = thread_su._mail_get_operation_for_mail_message_operation(
            "create"
        ).get(thread_su)
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
    def mail_thread_messages(self, thread_model, thread_id, fetch_params=None):
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
    def mail_thread_recipients(self, thread_model, thread_id, message_id=None):
        """Fetch discussion-based suggested recipients, creating partners on the fly
        only when the caller can write the record."""
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        # Only auto-create partners from the record's email fields when the caller
        # can write it: a read-only viewer must not spawn partners by fetching.
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
        #
        # Deliberately *not* ``_to_thread_model``: both methods below are
        # defined on ``Base`` (mail/models/base.py), so they answer for any
        # model. Narrowing this route to threads would reject callers that work
        # today, which is a behaviour change and not a 500 to fix.
        if thread_model not in request.env:
            raise NotFound
        model = request.env[thread_model]
        return {
            "partner_fields": model._mail_get_partner_fields(),
            "primary_email_field": [model._mail_get_primary_email_field()],
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
        # thread_model / thread_id are fully client-controlled: validate the model
        # (an unknown name KeyErrors into a 500) and bind to the record only when
        # the caller can read it. An inaccessible record falls back to the generic
        # lookup (_partner_find_from_emails_single supports a void recordset)
        # rather than deriving company/context from an unreachable thread.
        thread = _to_thread_model(thread_model)
        record_id = _to_record_id(thread_id)
        if record_id:
            thread = thread._get_thread_with_access(record_id, mode="read") or thread
        partners = thread._partner_find_from_emails_single(
            emails,
            no_create=not request.env.user.has_group("base.group_partner_manager"),
        )
        # The recordset is deduped and id-ordered, so it cannot be paired
        # positionally with ``emails``: echo the source address per partner.
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
        follower = request.env["mail.followers"].browse(_to_record_id(follower_id))
        follower.check_access("read")
        # 'mail.followers.res_model' carries no integrity check by design (see the
        # note on that field), so it can outlive the model it names. Answer 404
        # rather than dereferencing it into a KeyError.
        #
        # Registry membership is the right question here, unlike on the routes
        # guarded by ``_to_thread_model``: ``_mail_get_message_subtypes`` is a
        # ``Base`` method, so a live non-thread model still answers it.
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

    def _is_mentionable_in_thread(self, partner, thread):
        """Whether a mention token may add ``partner`` as a recipient of a
        message posted on ``thread``.

        The token is bound to (partner, "id", scope) and valid for weeks, so it
        proves the caller saw the partner but not *where*: since
        ``/discuss/channel/members`` serves member personas (tokens included) to
        anyone who can read the channel, one could be replayed on any thread.
        """
        # Channels only: elsewhere posting already requires access to the record,
        # and mentioning someone not yet involved is a legitimate chatter flow.
        if thread._name != "discuss.channel":
            return True
        # sudo: discuss.channel.member - checking membership of the very channel
        # the caller is posting to, to decide whether a mention is in-scope.
        channel_sudo = thread.sudo()
        channels = channel_sudo.parent_channel_id | channel_sudo
        return partner in channels.channel_member_ids.partner_id

    def _prepare_message_data(self, post_data, *, thread, from_create=True, **kwargs):
        """Build the message values for a post (``from_create=True``) or an edit.

        ``from_create`` is declared explicitly rather than read out of
        ``**kwargs`` because ``portal`` keys anonymous author attribution on
        it. A misspelled keyword is still absorbed by ``**kwargs`` and leaves
        the default in place.
        """
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
                # sudo - res.users: getting partners linked to the role is allowed.
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
            # Only a *new* message gets a default type: _message_update_content
            # ignores it today, but its docstring invites kwargs "to match
            # mail.message fields to update", so it could retype edited messages.
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
    def mail_thread_subscribe(self, res_model, res_id, partner_ids):
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
