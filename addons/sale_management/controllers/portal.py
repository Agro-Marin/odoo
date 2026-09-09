from odoo.exceptions import AccessError, MissingError
from odoo.http import request, route

from odoo.addons.sale.controllers import portal


class CustomerPortal(portal.CustomerPortal):
    @route(
        ["/my/orders/<int:order_id>/update_line_dict"],
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def portal_quote_option_update(
        self,
        order_id,
        line_id,
        access_token=None,
        remove=False,
        input_quantity=False,
        **kwargs,
    ):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
            return request.redirect("/my")

        if not order_sudo._can_be_edited_on_portal():
            return None

        order_line = request.env["sale.order.line"].sudo().browse(int(line_id)).exists()
        if (
            not order_line
            or order_line.order_id != order_sudo
            or not order_line._can_be_edited_on_portal()
        ):
            return None

        if input_quantity is not False:
            quantity = max(input_quantity, 0)
        else:
            number = -1 if remove else 1
            quantity = max((order_line.product_qty + number), 0)

        if order_line.product_type == "combo":
            combo_item_lines = order_line._get_lines_linked().filtered("combo_item_id")
            combo_item_lines.update({"product_qty": quantity})

        order_line.product_qty = quantity
        return None
