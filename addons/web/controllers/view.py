from odoo.exceptions import AccessError
from odoo.http import Controller, request, route
from odoo.tools.translate import _


class View(Controller):
    @route("/web/view/edit_custom", type="jsonrpc", auth="user")
    def edit_custom(self, custom_id: int, arch: str) -> dict[str, bool]:
        custom_view = request.env["ir.ui.view.custom"].sudo().browse(custom_id)
        if custom_view.user_id != request.env.user:
            raise AccessError(
                _(
                    "Custom view %(view)s does not belong to user %(user)s",
                    view=custom_id,
                    user=request.env.user.login,
                )
            )
        custom_view.write({"arch": arch})
        return {"result": True}
