from odoo.exceptions import AccessError
from odoo.http import Controller, request, route
from odoo.tools.translate import _


class View(Controller):
    @route("/web/view/edit_custom", type="jsonrpc", auth="user")
    def edit_custom(self, custom_id: int, arch: str) -> dict[str, bool]:
        """Overwrite the arch of a custom view owned by the current user.

        :param int custom_id: id of the custom view to update
        :param str arch: new arch to write to the view
        :returns: dict acknowledging the write (``{"result": True}``)
        :raises AccessError: if the view belongs to a different user
        """
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
