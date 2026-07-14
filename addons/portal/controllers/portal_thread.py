from werkzeug.exceptions import NotFound

from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.mail.controllers.thread import ThreadController, _to_record_id
from odoo.addons.mail.tools.discuss import EMPTY_EDIT_MARKER, Store
from odoo.addons.portal.utils import get_portal_partner


class PortalChatter(ThreadController):
    """Portal-facing chatter routes: avatar serving, message fetch, internal-flag toggle.

    Anonymous and portal-authenticated callers reach these routes; access is
    gated by HMAC token (``_hash`` + ``pid``) or per-thread ``access_token``,
    validated in :func:`portal.utils.get_portal_partner` / :mod:`mail.thread`.
    """

    @http.route(
        "/mail/avatar/mail.message/<int:res_id>/author_avatar/<int:width>x<int:height>",
        type="http",
        auth="public",
    )
    def portal_avatar(
        self, res_id=None, height=50, width=50, access_token=None, _hash=None, pid=None
    ):
        """Serve the chatter author avatar for portal-rendered threads.

        Validates the request against the thread (via token or HMAC). Any
        failure — invalid credentials, missing message, or no credentials at
        all — falls through to ``ir.binary``'s placeholder image rather than
        a 403 or 500, so the response does not leak whether ``res_id`` exists.
        """
        # Coerce ``pid`` once at entry: a non-numeric value resolves the same
        # as a missing pid (placeholder fallback below), so the response does
        # not leak whether ``res_id`` exists via a 500 from ``int(pid)``.
        try:
            pid = int(pid) if pid else None
        except ValueError:
            pid = None
        message_su = request.env["mail.message"]
        if access_token or (_hash and pid):
            # sudo: mail.message - look up the message before access validation;
            # _get_thread_with_access then validates token/HMAC. Guard against
            # an empty recordset: message_su.model would be False and
            # request.env[False] raises KeyError, returning 500 and leaking
            # res_id existence to unauthenticated callers.
            candidate_su = request.env["mail.message"].browse(res_id).exists().sudo()
            if candidate_su and self._get_thread_with_access(
                candidate_su.model,
                candidate_su.res_id,
                token=access_token,
                hash=_hash,
                pid=pid,
            ):
                message_su = candidate_su
        # Empty recordset triggers ir.binary's documented placeholder fallback
        # via _get_placeholder_filename — same bytes that ``web.image_placeholder``
        # used to resolve to, reached through the framework's intended path.
        stream = request.env["ir.binary"]._get_image_stream_from(
            message_su,
            field_name="author_avatar",
            width=int(width),
            height=int(height),
        )
        return stream.get_response()

    @http.route("/portal/chatter_init", type="jsonrpc", auth="public", website=True)
    def portal_chatter_init(self, thread_model, thread_id, **kwargs):
        """Build the initial Store payload for the portal chatter.

        Includes the current partner, optional portal_partner derived from
        HMAC/token, the thread itself, and whether the caller can react/post.
        """
        store = Store()
        request.env["res.users"]._init_store_data(store)
        # Optional dependency: when the `website` module is installed, mark the
        # current user as a publisher so the chatter shows the editor badge.
        # Safe to reference: has_group returns False when the xmlid is unknown.
        if request.env.user.has_group("website.group_website_restricted_editor"):
            store.add(request.env.user.partner_id, {"is_user_publisher": True})
        thread = self._get_thread_with_access(thread_model, thread_id, **kwargs)
        if thread:
            has_react_access = self._get_thread_with_access_for_post(
                thread_model, thread_id, **kwargs
            )
            can_react = has_react_access
            if request.env.user._is_public():
                if portal_partner := get_portal_partner(
                    thread,
                    kwargs.get("hash"),
                    kwargs.get("pid"),
                    kwargs.get("token"),
                ):
                    store.add(
                        thread,
                        {
                            "portal_partner": Store.One(
                                portal_partner,
                                fields=[
                                    "active",
                                    "avatar_128",
                                    Store.One("main_user_id", ["partner_id", "share"]),
                                    "name",
                                ],
                            )
                        },
                        as_thread=True,
                    )
                can_react = has_react_access and portal_partner
            store.add(
                thread,
                {
                    "can_react": bool(can_react),
                    # sudo(False) checks direct ACL access (no HMAC fallback).
                    # Lets the frontend distinguish token-only viewers from
                    # users with real read rights on the underlying record.
                    "hasReadAccess": thread.sudo(False).has_access("read"),
                },
                # display_name lets the frontend rebuild the prettified link of
                # a posted message thread after a page refresh.
                ["display_name"],
                as_thread=True,
            )
        return store.get_result()

    @http.route("/mail/chatter_fetch", type="jsonrpc", auth="public", website=True)
    def portal_message_fetch(self, thread_model, thread_id, fetch_params=None, **kw):
        """Fetch the messages displayed in the portal chatter.

        Builds the search domain from the thread model's ``website_message_ids``
        field and restricts it to the share-safe subset of messages
        (``_get_search_domain_share``) — i.e. non-internal messages of any
        non-internal subtype, not only ``mail.mt_comment``. All portal viewers,
        and internal users (who are meant to see the portal as portal users do),
        get the same non-internal-only visibility. Empty messages are dropped.
        For token-based auth, validates the token and rebinds ``Message`` to
        a sudo recordset so the search returns the messages the validator
        already authorised.
        """
        # ``thread_model`` is client-supplied: an unknown model or one that
        # does not carry the portal chatter field must be a clean 404, not a
        # KeyError bubbling up as "Odoo Server Error" (leaking model names).
        if thread_model not in request.env:
            raise NotFound
        model = request.env[thread_model]
        field = model._fields.get("website_message_ids")
        if field is None:
            raise NotFound
        # Coerce here too: the non-token path never calls _get_thread_with_access,
        # so a non-numeric thread_id would otherwise reach the ORM as
        # Domain("res_id", "=", "abc") and 500 with a ValueError.
        thread_id = _to_record_id(thread_id)
        domain = (
            Domain(self._setup_portal_message_fetch_extra_domain(kw))
            & Domain(field.get_comodel_domain(model))
            & Domain("res_id", "=", thread_id)
            & Domain(request.env["mail.message"]._get_search_domain_share())
            & self._get_non_empty_message_domain()
        )

        Message = request.env["mail.message"]
        if kw.get("token"):
            # Token-only access check (no hash/pid): the model's portal override
            # leaves its HMAC branch inert without hash+pid, so only the token is
            # validated here.
            thread = self._get_thread_with_access(
                thread_model,
                thread_id,
                token=kw.get("token"),
            )
            if not thread:
                raise NotFound
            if portal_partner := get_portal_partner(
                thread,
                _hash=None,
                pid=None,
                token=kw.get("token"),
            ):
                request.update_context(
                    portal_data={
                        "portal_partner": portal_partner,
                        "portal_thread": thread,
                    },
                )
            Message = request.env["mail.message"].sudo()
        res = Message._message_fetch(domain, **(fetch_params or {}))
        messages = res.pop("messages")
        return {
            **res,
            "data": {"mail.message": messages.portal_message_format(options=kw)},
            "messages": messages.ids,
        }

    def _get_non_empty_message_domain(self):
        """Filter out empty-body messages and the empty-edit-marker stub.

        The marker is the literal mail core inserts when an author removes
        all content from a previously-posted message. The canonical form is
        defined as :data:`mail.tools.discuss.EMPTY_EDIT_MARKER`.
        """
        return Domain(
            "body",
            "not in",
            [False, EMPTY_EDIT_MARKER],
        ) | Domain("attachment_ids", "!=", False)

    def _setup_portal_message_fetch_extra_domain(self, data) -> Domain:
        """Hook for downstream modules to add domain leaves to the portal message fetch."""
        return Domain.TRUE

    @http.route(["/mail/update_is_internal"], type="jsonrpc", auth="user", website=True)
    def portal_message_update_is_internal(self, message_id, is_internal):
        """Toggle the ``is_internal`` flag on a message.

        Access is gated by ``auth="user"`` (login required) and ``mail.message``
        ACL — the ``write()`` call below runs in the current user's env, so
        users who cannot write to the message are blocked by the ORM.
        """
        message = request.env["mail.message"].browse(_to_record_id(message_id))
        message.write({"is_internal": is_internal})
        return message.is_internal
