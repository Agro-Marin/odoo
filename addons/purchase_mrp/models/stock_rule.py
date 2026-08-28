from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _notify_responsible(self, procurement):
        super()._notify_responsible(procurement)
        references = procurement.values.get("reference_ids")
        origin_orders = references.production_ids if references else False
        if origin_orders:
            notified_users = (
                procurement.product_id.responsible_id.partner_id
                | origin_orders.user_id.partner_id
            )
            self._post_vendor_notification(
                origin_orders, notified_users, procurement.product_id
            )
