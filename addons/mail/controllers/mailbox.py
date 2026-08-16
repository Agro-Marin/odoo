from odoo import http
from odoo.http import request

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
        domain = [("needaction", "=", True)]
        res = request.env["mail.message"]._message_fetch(
            domain, **request.env["mail.message"]._sanitize_fetch_params(fetch_params)
        )
        messages = res.pop("messages")
        bus_last_id = request.env["bus.bus"].sudo()._bus_last_id()
        store = Store().add(
            messages,
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
        return {
            **res,
            "data": store.get_result(),
            "messages": messages.ids,
        }

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
        domain = [("notification_ids", "in", notification_ids)]
        res = request.env["mail.message"]._message_fetch(
            domain, **request.env["mail.message"]._sanitize_fetch_params(fetch_params)
        )
        messages = res.pop("messages")
        return {
            **res,
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }

    @http.route(
        "/mail/starred/messages",
        methods=["POST"],
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def discuss_starred_messages(self, fetch_params: dict | None = None) -> dict:
        domain = [("starred_partner_ids", "in", [request.env.user.partner_id.id])]
        res = request.env["mail.message"]._message_fetch(
            domain, **request.env["mail.message"]._sanitize_fetch_params(fetch_params)
        )
        messages = res.pop("messages")
        return {
            **res,
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }
