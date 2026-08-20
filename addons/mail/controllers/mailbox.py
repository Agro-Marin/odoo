from odoo import http
from odoo.http import request

from odoo.addons.mail.controllers.utils import message_fetch_response
from odoo.addons.mail.tools.discuss import Store


class MailboxController(http.Controller):
    @http.route(
        "/mail/inbox/messages",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def discuss_inbox_messages(self, fetch_params: dict | None = None) -> dict:
        bus_last_id = request.env["bus.bus"].sudo()._bus_last_id()
        return message_fetch_response(
            domain=[("needaction", "=", True)],
            fetch_params=fetch_params,
            extra_fields=[
                Store.One(
                    "thread",
                    [
                        Store.Attr("message_needaction_counter", sudo=True),
                        Store.Attr("message_needaction_counter_bus_id", bus_last_id),
                    ],
                    as_thread=True,
                )
            ],
            add_followers=True,
        )

    @http.route(
        "/mail/history/messages",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def discuss_history_messages(self, fetch_params: dict | None = None) -> dict:
        notification_ids = request.env["mail.notification"]._search(
            [
                ("res_partner_id", "=", request.env.user.partner_id.id),
                ("is_read", "=", True),
            ]
        )
        return message_fetch_response(
            domain=[("notification_ids", "in", notification_ids)],
            fetch_params=fetch_params,
        )

    @http.route(
        "/mail/starred/messages",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def discuss_starred_messages(self, fetch_params: dict | None = None) -> dict:
        return message_fetch_response(
            domain=[("starred_partner_ids", "in", [request.env.user.partner_id.id])],
            fetch_params=fetch_params,
        )
