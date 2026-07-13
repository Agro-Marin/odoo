from werkzeug.exceptions import BadRequest

from odoo.http import Controller, request, route
from odoo.libs.json import dumps, loads


class BusController(Controller):
    @route("/bus/get_model_definitions", methods=["POST"], type="http", auth="user")
    def get_model_definitions(self, model_names_to_fetch, **kwargs):
        model_names = loads(model_names_to_fetch)
        if not isinstance(model_names, list) or not all(
            isinstance(name, str) for name in model_names
        ):
            raise BadRequest("model_names_to_fetch must be a JSON array of strings")
        # An unknown model would raise KeyError deep in _get_model_definitions
        # — a 500 with a full traceback for what is client-controlled input.
        unknown = [name for name in model_names if name not in request.env]
        if unknown:
            raise BadRequest(f"Unknown models: {', '.join(sorted(unknown))}")
        return request.make_response(
            dumps(
                request.env["ir.model"]._get_model_definitions(model_names),
            )
        )

    @route("/bus/has_missed_notifications", type="jsonrpc", auth="public")
    def has_missed_notifications(self, last_notification_id):
        # A non-integer id (client-controlled JSON) would make the query
        # crash with a 500; reject it explicitly instead.
        if not isinstance(last_notification_id, int) or isinstance(
            last_notification_id, bool
        ):
            raise BadRequest("last_notification_id must be an integer")
        # sudo - bus.bus: checking if a notification still exists is allowed
        # to detect missed notifications during disconnect.
        request.env.cr.execute(
            "SELECT NOT EXISTS(SELECT 1 FROM bus_bus WHERE id = %s)",
            [last_notification_id],
        )
        return request.env.cr.fetchone()[0]
