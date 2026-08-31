from odoo import _, api, fields, models

from .exception_activity import group_by_order, notify_orders_of_exception


class SaleOrder(models.Model):
    _inherit = "sale.order"

    purchase_order_count = fields.Integer(
        "Number of Purchase Order Generated",
        compute="_compute_purchase_order_count",
        groups="purchase.group_purchase_user",
    )

    @api.depends("line_ids.purchase_line_ids.order_id")
    def _compute_purchase_order_count(self):
        for order in self:
            order.purchase_order_count = len(order._get_purchase_orders())

    def _action_confirm(self):
        result = super()._action_confirm()
        self.line_ids.sudo()._purchase_service_generation()
        return result

    def _action_cancel(self):
        result = super()._action_cancel()
        # When a sale person cancel a SO, he might not have the rights to write
        # on PO. But we need the system to create an activity on the PO (so 'write'
        # access), hence the `sudo`.
        self.sudo()._activity_cancel_on_purchase()
        return result

    def action_view_purchase_orders(self):
        self.check_singleton()
        purchase_orders = self._get_purchase_orders()
        title = (
            {"name": _("Purchase Order generated from %s", self.name)}
            if len(purchase_orders) > 1
            else {}
        )
        return purchase_orders._get_records_action(**title)

    def _get_purchase_orders(self):
        return self.line_ids.purchase_line_ids.order_id

    def _activity_cancel_on_purchase(self):
        """If some SO are cancelled, we need to put an activity on their generated purchase. If sale lines of
        different sale orders impact different purchase, we only want one activity to be attached.
        """
        purchase_lines = self.line_ids.purchase_line_ids.filtered(
            lambda pol: pol.state != "cancel"
        )
        notify_orders_of_exception(
            group_by_order(purchase_lines, lambda pol: pol.order_id),
            "sale_purchase.exception_purchase_on_sale_cancellation",
            lambda lines: {
                "sale_orders": lines.sale_line_id.order_id,
                "sale_order_lines": lines.sale_line_id,
            },
        )
