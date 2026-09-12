from odoo import http
from odoo.http import request

from ..tools import debug_log as dbg
from odoo.addons.web.controllers.binary import Binary


class PointOfSaleBinary(Binary):
    @http.route(
        [
            "/web/image/pos.config/<id>/<string:field>",
            "/web/image/pos.config/<id>/<string:field>/<int:width>x<int:height>",
        ],
        type="http",
        auth="public",
    )
    def point_of_sale_content_image(self, field="raw", **kwargs):
        if request.env.user._is_public() and field == "customer_display_bg_img":
            dbg.logic.debug(
                "[http] public customer_display_bg_img on pos.config %s: sudo",
                kwargs.get("id"),
            )
            request.env = request.env(su=True)
        return super().content_image(field=field, model="pos.config", **kwargs)
