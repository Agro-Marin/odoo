from typing import Any

from markupsafe import Markup
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.mail.controllers.utils import (
    clamp_limit,
    get_channel_or_404,
    get_self_member,
    get_self_member_or_404,
    message_fetch_response,
    to_record_id,
    to_record_ids,
)
from odoo.addons.mail.controllers.webclient import WebclientController
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

MAX_AVATAR_B64_BYTES = 10 * 1024 * 1024


class DiscussChannelWebclientController(WebclientController):
    @classmethod
    def _process_request_loop(
        cls, store: Store, fetch_params: list[str | list]
    ) -> None:
        request.update_context(
            channels=request.env["discuss.channel"], add_channels_last_message=False
        )
        super()._process_request_loop(store, fetch_params)
        channels = request.env.context["channels"]
        if channels:
            store.add(channels)
        if request.env.context["add_channels_last_message"]:
            store.add(channels._get_last_messages())

    @classmethod
    def _process_request_for_all(cls, store: Store, name: str, params: Any) -> None:
        super()._process_request_for_all(store, name, params)
        if name == "init_messaging":
            member_domain = [
                ("is_self", "=", True),
                ("rtc_inviting_session_id", "!=", False),
            ]
            channel_domain = [("channel_member_ids", "any", member_domain)]
            channels = request.env["discuss.channel"].search(channel_domain)
            request.update_context(channels=request.env.context["channels"] | channels)
        if name == "channels_as_member":
            channels = request.env["discuss.channel"]._get_channels_as_member()
            request.update_context(
                channels=request.env.context["channels"] | channels,
                add_channels_last_message=True,
            )
        if name == "discuss.channel":
            channels = request.env["discuss.channel"].search([("id", "in", params)])
            request.update_context(channels=request.env.context["channels"] | channels)
        if name == "/discuss/get_or_create_chat":
            channel = request.env["discuss.channel"]._get_or_create_chat(
                params["partners_to"], params.get("pin", True)
            )
            store.add(channel).resolve_data_request(channel=Store.One(channel, []))
        if name == "/discuss/create_channel":
            channel = request.env["discuss.channel"]._create_channel(
                params["name"], params["group_id"]
            )
            store.add(channel).resolve_data_request(channel=Store.One(channel, []))
        if name == "/discuss/create_group":
            channel = request.env["discuss.channel"]._create_group(
                params["partners_to"],
                params.get("default_display_mode", False),
                params.get("name", ""),
            )
            store.add(channel).resolve_data_request(channel=Store.One(channel, []))


class ChannelController(http.Controller):
    @http.route(
        "/discuss/channel/members",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
        readonly=True,
    )
    @add_guest_to_context
    def discuss_channel_members(
        self, channel_id: int, known_member_ids: list[int], limit: int = 100
    ) -> dict:
        channel = get_channel_or_404(channel_id)
        unknown_members = request.env["discuss.channel.member"].search(
            domain=[
                ("id", "not in", to_record_ids(known_member_ids)),
                ("channel_id", "=", channel.id),
            ],
            limit=clamp_limit(limit, default=100),
        )
        store = Store().add(channel, "member_count").add(unknown_members)
        return store.get_result()

    @http.route(
        "/discuss/channel/update_avatar", methods=["POST"], type="jsonrpc", auth="user"
    )
    def discuss_channel_avatar_update(self, channel_id: int, data: str) -> None:
        channel = get_channel_or_404(channel_id)
        if not data or not isinstance(data, str):
            raise NotFound
        if len(data) > MAX_AVATAR_B64_BYTES:
            raise UserError(request.env._("The avatar image is too large."))
        channel.write({"image_128": data})

    @http.route(
        "/discuss/channel/messages", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def discuss_channel_messages(
        self, channel_id: int, fetch_params: dict | None = None
    ) -> dict:
        channel = get_channel_or_404(channel_id)
        return message_fetch_response(
            thread=channel, fetch_params=fetch_params, mark_done=True
        )

    @http.route(
        "/discuss/channel/pinned_messages",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
        readonly=True,
    )
    @add_guest_to_context
    def discuss_channel_pins(self, channel_id: int) -> dict:
        channel = get_channel_or_404(channel_id)
        messages = channel.pinned_message_ids.sorted(key="pinned_at", reverse=True)
        return Store().add(messages).get_result()

    @http.route(
        "/discuss/channel/mark_as_read", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def discuss_channel_mark_as_read(
        self, channel_id: int, last_message_id: int
    ) -> None:
        member = get_self_member(channel_id)
        if not member:
            return
        member._mark_as_read(to_record_id(last_message_id))

    @http.route(
        "/discuss/channel/set_new_message_separator",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_set_new_message_separator(
        self, channel_id: int, message_id: int
    ) -> None:
        member = get_self_member_or_404(channel_id)
        return member._set_new_message_separator(to_record_id(message_id))

    @http.route(
        "/discuss/channel/notify_typing",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_notify_typing(self, channel_id: int, is_typing: bool) -> None:
        channel = get_channel_or_404(channel_id)
        is_typing = bool(is_typing)
        if is_typing:
            member = channel._get_or_create_member_for_self()
        else:
            member = get_self_member(channel.id)
        if member:
            member._notify_typing(is_typing)

    @http.route(
        "/discuss/channel/attachments",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
        readonly=True,
    )
    @add_guest_to_context
    def load_attachments(
        self, channel_id: int, limit: int = 30, before: int | None = None
    ) -> dict:
        channel = get_channel_or_404(channel_id)
        domain = [
            ["res_id", "=", channel.id],
            ["res_model", "=", "discuss.channel"],
        ]
        if before:
            domain.append(["id", "<", to_record_id(before)])
        page_size = clamp_limit(limit)
        attachments = (
            request.env["ir.attachment"]
            .sudo()
            .search(domain, limit=page_size + 1, order="id DESC")
        )
        has_more = len(attachments) > page_size
        attachments = attachments[:page_size]
        return {
            "store_data": Store().add(attachments).get_result(),
            "count": len(attachments),
            "has_more": has_more,
        }

    @http.route(
        "/discuss/channel/join", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def discuss_channel_join(self, channel_id: int) -> dict:
        channel = get_channel_or_404(channel_id)
        channel._get_or_create_member_for_self()
        return Store().add(channel).get_result()

    @http.route(
        "/discuss/channel/sub_channel/create",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_sub_channel_create(
        self,
        parent_channel_id: int,
        from_message_id: int | None = None,
        name: str | None = None,
    ) -> dict:
        channel = get_channel_or_404(parent_channel_id)
        sub_channel = channel._create_sub_channel(
            to_record_id(from_message_id) if from_message_id else None, name
        )
        return {
            "store_data": Store().add(sub_channel).get_result(),
            "sub_channel": sub_channel.id,
        }

    @http.route(
        "/discuss/channel/sub_channel/fetch",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_sub_channel_fetch(
        self,
        parent_channel_id: int,
        search_term: str | None = None,
        before: int | None = None,
        limit: int = 30,
    ) -> dict:
        channel = get_channel_or_404(parent_channel_id)
        domain = [("parent_channel_id", "=", channel.id)]
        if before:
            domain.append(("id", "<", to_record_id(before)))
        if search_term:
            domain.append(("name", "ilike", search_term))
        sub_channels = request.env["discuss.channel"].search(
            domain, order="id desc", limit=clamp_limit(limit)
        )
        return {
            "store_data": Store()
            .add(sub_channels)
            .add(sub_channels._get_last_messages())
            .get_result(),
            "sub_channel_ids": sub_channels.ids,
        }

    @http.route(
        "/discuss/channel/sub_channel/delete",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
    )
    def discuss_delete_sub_channel(self, sub_channel_id: int) -> None:
        channel = request.env["discuss.channel"].search_fetch(
            [("id", "=", to_record_id(sub_channel_id))]
        )
        if (
            not channel
            or not channel.parent_channel_id
            or channel.create_uid != request.env.user
        ):
            raise NotFound
        body = (
            Markup(
                '<div class="o_mail_notification" data-oe-type="thread_deletion">%s</div>'
            )
            % channel.name
        )
        channel.parent_channel_id.message_post(
            body=body, subtype_xmlid="mail.mt_comment"
        )
        channel.sudo().unlink()
