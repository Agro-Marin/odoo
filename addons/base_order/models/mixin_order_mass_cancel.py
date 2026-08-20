from odoo import api, fields, models


class MixinOrderMassCancel(models.AbstractModel):
    """Cancel several orders at once from a list selection.

    The concrete wizards declare ``order_ids`` themselves — a Many2many needs a
    comodel, so it cannot live here — and inherit everything else. Following
    ``mixin.order``, the computes below depend on a field this mixin does not
    declare; it resolves on the concrete model.
    """

    _name = "mixin.order.mass.cancel"
    _description = "Cancel Multiple Orders"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    orders_count = fields.Integer(compute="_compute_orders_count")
    has_confirmed_order = fields.Boolean(compute="_compute_has_confirmed_order")

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("order_ids")
    def _compute_orders_count(self):
        for wizard in self:
            wizard.orders_count = len(wizard.order_ids)

    @api.depends("order_ids")
    def _compute_has_confirmed_order(self):
        for wizard in self:
            wizard.has_confirmed_order = bool(
                wizard.order_ids.filtered(lambda order: order.state == "done"),
            )

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def action_mass_cancel(self):
        # Skip orders already cancelled (so a mixed selection doesn't abort on
        # the "already cancelled" guard), but route through the public
        # action_cancel so every _can_cancel guard still applies — the locked
        # check for both order types, plus purchase's posted-bill check.
        # Calling _action_cancel() directly would bypass them and cancel a
        # locked or already-invoiced order silently.
        self.order_ids.filtered(lambda order: order.state != "cancel").action_cancel()
        return {"type": "ir.actions.act_window_close"}
