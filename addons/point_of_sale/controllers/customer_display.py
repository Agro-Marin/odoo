from odoo import http
from odoo.http import request


class PosCustomerDisplay(http.Controller):
    @http.route(
        "/pos_customer_display/<id_>/<device_uuid>",
        auth="public",
        type="http",
        website=True,
    )
    def pos_customer_display(self, id_, device_uuid, **kw):
        # This route is public and reachable by enumerable integer id. Reject
        # non-numeric ids, non-existent configs, and configs without an active
        # session so the access_token / customer-display payload is not handed
        # out for arbitrary ids. The customer display is only opened from a
        # running POS session, so requiring an active session is safe.
        try:
            config_id = int(id_)
        except TypeError, ValueError:
            return request.not_found()
        pos_config_sudo = request.env["pos.config"].sudo().browse(config_id)
        if not pos_config_sudo.exists() or not pos_config_sudo.has_active_session:
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
