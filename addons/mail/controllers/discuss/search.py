from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.mail.controllers.utils import clamp_limit
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context


class SearchController(http.Controller):
    @http.route(
        "/discuss/search",
        methods=["POST"],
        type="jsonrpc",
        auth="public",
        readonly=True,
    )
    @add_guest_to_context
    def search(self, term: str, limit: int = 10) -> dict:
        limit = clamp_limit(limit, default=10)
        store = Store()
        self.get_search_store(store, search_term=term, limit=limit)
        return store.get_result()

    def get_search_store(self, store: Store, search_term: str, limit: int) -> None:
        base_domain = Domain("name", "ilike", search_term) & Domain(
            "channel_type", "!=", "chat"
        )
        priority_conditions = [
            Domain("is_member", "=", True) & base_domain,
            base_domain,
        ]
        channels = request.env["discuss.channel"]
        for domain in priority_conditions:
            remaining_limit = limit - len(channels)
            if remaining_limit <= 0:
                break
            query = channels._search(
                Domain("id", "not in", channels.ids) & domain, limit=remaining_limit
            )
            channels |= channels.browse(query)
        store.add(channels)
        if not request.env.user._is_public():
            request.env["res.partner"]._search_for_channel_invite(
                store, search_term=search_term, limit=limit
            )
