from werkzeug.exceptions import BadRequest

from odoo.http import Controller, request, route
from odoo.libs.json import dumps, loads


class BusController(Controller):
    """HTTP endpoints for bus metadata and reconnect detection."""

    @route("/bus/get_model_definitions", methods=["POST"], type="http", auth="user")
    def get_model_definitions(self, model_names_to_fetch: str, **kwargs):
        """Return field definitions for the requested models.

        Used by the JS client to build local model mirrors.
        """
        names = loads(model_names_to_fetch)
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise BadRequest("model_names_to_fetch must be a JSON array of strings")
        return request.make_response(
            dumps(request.env["ir.model"]._get_model_definitions(names))
        )

    @route("/bus/has_missed_notifications", type="jsonrpc", auth="public")
    def has_missed_notifications(self, last_notification_id: int) -> bool:
        """Check whether a notification has been garbage-collected.

        Returns ``True`` when the notification no longer exists in the bus
        table, signalling the client that it may have missed messages during
        a disconnect and should refetch state.
        """
        # sudo - bus.bus: checking if a notification still exists in order to
        # detect missed notification during disconnect is allowed.
        request.env.cr.execute(
            "SELECT NOT EXISTS(SELECT 1 FROM bus_bus WHERE id = %s)",
            [last_notification_id],
        )
        return request.env.cr.fetchone()[0]
