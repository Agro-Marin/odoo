import re
import typing
from typing import Literal

import psycopg.errors
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import UserError
from odoo.http import Response, request
from odoo.tools import consteq, email_normalize, replace_exceptions
from odoo.tools.misc import verify_hash_signed

from odoo.addons.mail.controllers.utils import get_channel_or_404
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

if typing.TYPE_CHECKING:
    from odoo.addons.mail.models.discuss.discuss_channel import DiscussChannel


_CREATE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


def _is_plausible_create_token(create_token: str) -> bool:
    return isinstance(create_token, str) and bool(_CREATE_TOKEN_RE.match(create_token))


class PublicPageController(http.Controller):
    @http.route(
        [
            "/chat/<string:create_token>",
            "/chat/<string:create_token>/<string:channel_name>",
        ],
        methods=["GET"],
        type="http",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_chat_from_token(
        self, create_token: str, channel_name: str | None = None
    ) -> Response:
        return self._response_discuss_channel_from_token(
            create_token=create_token, channel_name=channel_name
        )

    @http.route(
        [
            "/meet/<string:create_token>",
            "/meet/<string:create_token>/<string:channel_name>",
        ],
        methods=["GET"],
        type="http",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_meet_from_token(
        self, create_token: str, channel_name: str | None = None
    ) -> Response:
        return self._response_discuss_channel_from_token(
            create_token=create_token,
            channel_name=channel_name,
            default_display_mode="video_full_screen",
        )

    @http.route(
        "/chat/<int:channel_id>/<string:invitation_token>",
        methods=["GET"],
        type="http",
        auth="public",
    )
    @add_guest_to_context
    def discuss_channel_invitation(
        self, channel_id: int, invitation_token: str, email_token: str | None = None
    ) -> Response:
        guest_email = email_token and verify_hash_signed(
            self.env(su=True), "mail.invite_email", email_token
        )
        guest_email = email_normalize(guest_email)
        channel = request.env["discuss.channel"].browse(channel_id).exists()
        if (
            not channel
            or not channel.sudo().uuid
            or not consteq(channel.sudo().uuid, invitation_token)
        ):
            raise NotFound
        store = Store().add_global_values(isChannelTokenSecret=True)
        return self._response_discuss_channel_invitation(store, channel, guest_email)

    @http.route(
        "/discuss/channel/<int:channel_id>", methods=["GET"], type="http", auth="public"
    )
    @add_guest_to_context
    def discuss_channel(self, channel_id: int) -> Response:
        channel = get_channel_or_404(channel_id)
        return self._response_discuss_public_template(Store(), channel)

    def _response_discuss_channel_from_token(
        self,
        create_token: str,
        channel_name: str | None = None,
        default_display_mode: str | Literal[False] = False,
    ) -> Response:
        if (
            not request.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.chat_from_token")
        ):
            raise NotFound
        channel_sudo = (
            request.env["discuss.channel"].sudo().search([("uuid", "=", create_token)])
        )
        if not channel_sudo and not _is_plausible_create_token(create_token):
            raise NotFound
        if not channel_sudo:
            try:
                with request.env.cr.savepoint():
                    channel_sudo = channel_sudo.create(
                        {
                            "channel_type": "channel",
                            "default_display_mode": default_display_mode,
                            "group_public_id": None,
                            "name": channel_name or create_token,
                            "uuid": create_token,
                        }
                    )
            except psycopg.errors.UniqueViolation:
                channel_sudo = channel_sudo.search([("uuid", "=", create_token)])
        store = Store().add_global_values(isChannelTokenSecret=False)
        return self._response_discuss_channel_invitation(
            store, channel_sudo.sudo(False)
        )

    def _response_discuss_channel_invitation(
        self, store: Store, channel: DiscussChannel, guest_email: str | None = None
    ) -> Response:
        group_public_id = (
            channel.group_public_id or channel.parent_channel_id.sudo().group_public_id
        )
        if group_public_id and group_public_id not in request.env.user.all_group_ids:
            raise NotFound
        guest_already_known = channel.env["mail.guest"]._get_guest_from_context()
        with replace_exceptions(UserError, by=NotFound()):
            __, guest = channel.sudo()._get_or_create_persona_for_channel(
                guest_name=guest_email or request.env._("Guest"),
                country_code=request.geoip.country_code,
                timezone=request.env["mail.guest"]._get_timezone_from_request(request),
            )
        if guest_email and not guest.email:
            guest.sudo().email = guest_email
        if guest and not guest_already_known:
            store.add_global_values(is_welcome_page_displayed=True)
            channel = channel.with_context(guest=guest)
        return self._response_discuss_public_template(store, channel)

    def _response_discuss_public_template(
        self, store: Store, channel: DiscussChannel
    ) -> Response:
        store.add_global_values(
            companyName=request.env.company.name,
            inPublicPage=True,
        )
        store.add_singleton_values("DiscussApp", {"thread": store.One(channel)})
        return request.render(
            "mail.discuss_public_channel_template",
            {
                "data": store.get_result(),
                "session_info": channel.env["ir.http"].session_info(),
            },
        )
