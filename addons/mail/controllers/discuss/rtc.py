from collections import defaultdict

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import Response, request
from odoo.tools import file_open

from odoo.addons.mail.controllers.thread import (
    _to_record_id,
    _to_record_ids,
    _to_record_ids_strict,
)
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

_MAX_PEER_NOTIFICATIONS = 100
_MAX_PEER_CONTENT_LEN = 100_000


class RtcController(http.Controller):
    @http.route(
        "/mail/rtc/session/notify_call_members",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def session_call_notify(self, peer_notifications: list) -> None:
        guest = request.env["mail.guest"]._get_guest_from_context()
        if not isinstance(peer_notifications, (list, tuple)):
            raise NotFound
        notifications_by_session = defaultdict(list)
        for notification in peer_notifications[:_MAX_PEER_NOTIFICATIONS]:
            if not isinstance(notification, (list, tuple)) or len(notification) != 3:
                continue
            sender_session_id, target_session_ids, content = notification
            if isinstance(content, str) and len(content) > _MAX_PEER_CONTENT_LEN:
                continue
            session_sudo = (
                request.env["discuss.channel.rtc.session"]
                .sudo()
                .browse(_to_record_id(sender_session_id))
                .exists()
            )
            if (
                not session_sudo
                or (session_sudo.guest_id and session_sudo.guest_id != guest)
                or (
                    session_sudo.partner_id
                    and session_sudo.partner_id != request.env.user.partner_id
                )
            ):
                continue
            notifications_by_session[session_sudo].append(
                (_to_record_ids(target_session_ids), content)
            )
        for session_sudo, notifications in notifications_by_session.items():
            session_sudo._notify_peers(notifications)

    @http.route(
        "/mail/rtc/session/update_and_broadcast",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def session_update_and_broadcast(self, session_id: int, values: dict) -> None:
        if request.env.user._is_public():
            guest = request.env["mail.guest"]._get_guest_from_context()
            if guest:
                session = (
                    guest.env["discuss.channel.rtc.session"]
                    .sudo()
                    .browse(_to_record_id(session_id))
                    .exists()
                )
                if session and session.guest_id == guest:
                    session._update_and_broadcast(values)
                    return
            return
        session = (
            request.env["discuss.channel.rtc.session"]
            .sudo()
            .browse(_to_record_id(session_id))
            .exists()
        )
        if session and session.partner_id == request.env.user.partner_id:
            session._update_and_broadcast(values)

    @http.route(
        "/mail/rtc/channel/join_call", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def channel_call_join(
        self,
        channel_id: int,
        check_rtc_session_ids: list[int] | None = None,
        camera: bool = False,
    ) -> dict:
        channel = request.env["discuss.channel"].search(
            [("id", "=", _to_record_id(channel_id))]
        )
        if not channel:
            raise request.not_found()
        member = channel._find_or_create_member_for_self()
        if not member:
            raise NotFound
        store = Store()
        member.sudo()._rtc_join_call(
            store, check_rtc_session_ids=check_rtc_session_ids, camera=camera
        )
        return store.get_result()

    @http.route(
        "/mail/rtc/channel/leave_call", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def channel_call_leave(
        self, channel_id: int, session_id: int | None = None
    ) -> None:
        member = request.env["discuss.channel.member"].search(
            [("channel_id", "=", _to_record_id(channel_id)), ("is_self", "=", True)]
        )
        if not member:
            raise NotFound
        member.sudo()._rtc_leave_call(session_id)

    @http.route(
        "/mail/rtc/channel/upgrade_connection",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
    )
    def channel_upgrade(self, channel_id: int) -> None:
        member = request.env["discuss.channel.member"].search(
            [("channel_id", "=", _to_record_id(channel_id)), ("is_self", "=", True)]
        )
        if not member:
            raise NotFound
        member.sudo()._join_sfu(force=True)

    @http.route(
        "/mail/rtc/channel/cancel_call_invitation",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
    )
    @add_guest_to_context
    def channel_call_cancel_invitation(
        self, channel_id: int, member_ids: list[int] | None = None
    ) -> None:
        channel = request.env["discuss.channel"].search(
            [("id", "=", _to_record_id(channel_id))]
        )
        if not channel:
            raise NotFound
        if not channel.self_member_id:
            raise NotFound
        channel.sudo()._rtc_cancel_invitations(
            member_ids=_to_record_ids_strict(member_ids) if member_ids else None
        )

    @http.route(
        "/mail/rtc/audio_worklet_processor_v2",
        methods=["GET"],
        type="http",
        auth="public",
        readonly=True,
    )
    def audio_worklet_processor(self) -> Response:
        with file_open("mail/static/src/worklets/audio_processor.js", "rb") as f:
            data = f.read()
        return request.make_response(
            data,
            headers=[
                ("Content-Type", "application/javascript"),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", f"max-age={http.STATIC_CACHE}"),
            ],
        )

    @http.route(
        "/discuss/channel/ping", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def channel_ping(
        self,
        channel_id: int,
        rtc_session_id: int | None = None,
        check_rtc_session_ids: list[int] | None = None,
    ) -> dict:
        member = request.env["discuss.channel.member"].search(
            [("channel_id", "=", _to_record_id(channel_id)), ("is_self", "=", True)]
        )
        if not member:
            raise NotFound
        channel_member_sudo = member.sudo()
        if rtc_session_id:
            domain = [
                ("id", "=", _to_record_id(rtc_session_id)),
                ("channel_member_id", "=", member.id),
            ]
            channel_member_sudo.channel_id.rtc_session_ids.filtered_domain(
                domain
            ).write({})
        current_rtc_sessions, outdated_rtc_sessions = (
            channel_member_sudo._rtc_sync_sessions(check_rtc_session_ids)
        )
        return (
            Store()
            .add(
                member.channel_id,
                [
                    {"rtc_session_ids": Store.Many(current_rtc_sessions, mode="ADD")},
                    {
                        "rtc_session_ids": Store.Many(
                            outdated_rtc_sessions, [], mode="DELETE"
                        )
                    },
                ],
            )
            .get_result()
        )
