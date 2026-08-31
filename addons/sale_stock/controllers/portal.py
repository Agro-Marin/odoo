from werkzeug.exceptions import NotFound

from odoo import exceptions
from odoo.http import request, route
from odoo.tools import consteq

from odoo.addons.sale.controllers.portal import CustomerPortal


class SaleStockPortal(CustomerPortal):
    def _stock_picking_check_access(self, picking_id, access_token=None):
        picking = request.env["stock.picking"].browse(picking_id)
        picking_sudo = picking.sudo()
        try:
            picking.check_access("read")
        except exceptions.AccessError:
            if (
                not access_token
                or not picking_sudo.sale_id
                or not consteq(picking_sudo.sale_id.access_token, access_token)
            ):
                raise
        return picking_sudo

    def _render_picking_pdf(self, report_xmlid, picking_id, access_token=None):
        try:
            picking_sudo = self._stock_picking_check_access(
                picking_id, access_token=access_token
            )
        except exceptions.AccessError, exceptions.MissingError:
            return NotFound()

        pdf = (
            request.env["ir.actions.report"]
            .sudo()
            ._render_qweb_pdf(report_xmlid, [picking_sudo.id])[0]
        )
        return request.prepare_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", len(pdf)),
            ],
        )

    @route(
        ["/my/picking/pdf/<int:picking_id>"], type="http", auth="public", website=True
    )
    def portal_my_picking_report(self, picking_id, access_token=None, **kw):
        return self._render_picking_pdf(
            "stock.action_report_delivery", picking_id, access_token=access_token
        )

    @route(
        ["/my/picking/return/pdf/<int:picking_id>"],
        type="http",
        auth="public",
        website=True,
    )
    def portal_my_picking_return_report(self, picking_id, access_token=None, **kw):
        return self._render_picking_pdf(
            "stock.return_label_report", picking_id, access_token=access_token
        )
