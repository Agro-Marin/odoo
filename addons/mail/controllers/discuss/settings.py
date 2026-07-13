from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.http import Controller, request, route


class DiscussSettingsController(Controller):
    @route("/discuss/settings/mute", methods=["POST"], type="jsonrpc", auth="user")
    def discuss_mute(self, minutes, channel_id):
        """Mute notifications for the given number of minutes.
        :param minutes: (integer) number of minutes to mute notifications, -1 means mute until the user unmutes
        :param channel_id: (integer) id of the discuss.channel record
        """
        # search (not browse): browse returns a truthy recordset for any int,
        # so a non-existent/inaccessible id would slip past the guard and 500 in
        # member creation instead of returning a clean 404 (as the sibling
        # /custom_notifications route does).
        channel = request.env["discuss.channel"].search([("id", "=", channel_id)])
        if not channel:
            raise request.not_found()
        member = channel._find_or_create_member_for_self()
        if not member:
            raise request.not_found()
        if minutes == -1:
            member.mute_until_dt = datetime.max  # noqa: DTZ901
        elif minutes:
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
    def discuss_custom_notifications(self, custom_notifications, channel_id=None):
        """Set custom notifications for the given channel or general user settings.
        :param custom_notifications: (false|all|mentions|no_notif) custom notifications to set
        :param channel_id: (integer) id of the discuss.channel record, if not set, set for res.users.settings
        """
        # Validate against the Selection values before writing: an arbitrary
        # string would otherwise raise ValueError deep in the ORM write -> 500.
        # The per-member field allows "mentions"; the user-settings one does not.
        allowed = (
            {False, "all", "mentions", "no_notif"}
            if channel_id
            else {False, "all", "no_notif"}
        )
        if custom_notifications not in allowed:
            raise request.not_found()
        if channel_id:
            channel = request.env["discuss.channel"].search([("id", "=", channel_id)])
            if not channel:
                raise request.not_found()
            member = channel._find_or_create_member_for_self()
            if not member:
                raise request.not_found()
            member.custom_notifications = custom_notifications
        else:
            user_settings = request.env["res.users.settings"]._find_or_create_for_user(
                request.env.user
            )
            if not user_settings:
                raise request.not_found()
            user_settings.set_res_users_settings(
                {"channel_notifications": custom_notifications}
            )
