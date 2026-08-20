from datetime import datetime
from typing import Literal

from dateutil.relativedelta import relativedelta
from werkzeug.exceptions import NotFound

from odoo import fields
from odoo.http import Controller, request, route

from odoo.addons.mail.controllers.utils import get_channel_or_404

MAX_MUTE_MINUTES = 525_600_000


class DiscussSettingsController(Controller):
    @route("/discuss/settings/mute", methods=["POST"], type="jsonrpc", auth="user")
    def discuss_mute(self, minutes: int, channel_id: int) -> None:
        channel = get_channel_or_404(channel_id)
        member = channel._find_or_create_member_for_self()
        if not member:
            raise NotFound
        if minutes == -1:
            member.mute_until_dt = datetime.max  # noqa: DTZ901
        elif minutes:
            if isinstance(minutes, bool) or not isinstance(minutes, (int, str)):
                raise NotFound
            try:
                minutes = int(minutes)
            except ValueError:
                raise NotFound from None
            if not 0 < minutes <= MAX_MUTE_MINUTES:
                raise NotFound
            member.mute_until_dt = fields.Datetime.now() + relativedelta(
                minutes=minutes
            )
        else:
            member.mute_until_dt = False
        member._notify_mute()

    @route(
        "/discuss/settings/custom_notifications",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
    )
    def discuss_custom_notifications(
        self,
        custom_notifications: str | Literal[False],
        channel_id: int | None = None,
    ) -> None:
        allowed = (
            {False, "all", "mentions", "no_notif"}
            if channel_id
            else {False, "all", "no_notif"}
        )
        if custom_notifications not in allowed:
            raise NotFound
        if channel_id:
            channel = get_channel_or_404(channel_id)
            member = channel._find_or_create_member_for_self()
            if not member:
                raise NotFound
            member.custom_notifications = custom_notifications
        else:
            user_settings = request.env["res.users.settings"]._find_or_create_for_user(
                request.env.user
            )
            if not user_settings:
                raise NotFound
            user_settings.set_res_users_settings(
                {"channel_notifications": custom_notifications}
            )
