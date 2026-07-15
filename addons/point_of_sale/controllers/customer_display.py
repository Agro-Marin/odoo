from odoo import http
from odoo.http import request
from odoo.tools import consteq


class PosCustomerDisplay(http.Controller):
    @http.route(
        "/pos_customer_display/<id_>/<device_uuid>",
        auth="public",
        type="http",
        website=True,
    )
    def pos_customer_display(self, id_, device_uuid, access_token=None, **kw):
        # Public, enumerable-id route. Reject non-numeric ids, non-existent
        # configs, configs without an active session, and — crucially —
        # callers that do not present the config's access_token. Without the
        # token check the payload (which carries access_token + proxy_ip) was
        # handed to any anonymous caller who guessed an id while a session was
        # open (all day in retail): R6-3 / t23962. The token travels in the QR
        # the authenticated POS operator generates, so a real display has it.
        try:
            config_id = int(id_)
        except TypeError, ValueError:
            return request.not_found()
        pos_config_sudo = request.env["pos.config"].sudo().browse(config_id)
        if (
            not pos_config_sudo.exists()
            or not pos_config_sudo.has_active_session
            or not access_token
            or not consteq(access_token, pos_config_sudo.access_token or "")
        ):
            return request.not_found()
        return request.render(
            "point_of_sale.customer_display_index",
            {
                "session_info": {
                    "user_context": {
                        "lang": request.env.user.lang
                        or pos_config_sudo.company_id.partner_id.lang
                    },
                    **request.env["ir.http"].get_frontend_session_info(),
                    **pos_config_sudo._get_customer_display_data(),
                    "device_uuid": device_uuid,
                },
            },
        )
