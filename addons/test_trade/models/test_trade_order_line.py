from odoo import fields, models

from odoo.addons.trade.tools import SALE


class TestTradeOrderLine(models.Model):
    _name = "test_trade.order.line"
    _inherit = [
        "mixin.order.line.fields",
        "mixin.order.line.amount",
        "mixin.analytic",
    ]
    _description = "Base Order Test Line"

    # FIELDS

    # Only ``comodel_name`` differs from ``mixin.order.line.fields``, which
    # also supplies the bridge fields (company_id, currency_id, state,
    # partner_id, locked, …) — as in the real sale/purchase lines.
    order_id = fields.Many2one(
        comodel_name="test_trade.order",
        string="Order",
    )

    # Self-referential section link: the compute lives in the mixin, but the
    # comodel must point to this concrete line model (as in sale/purchase).
    parent_id = fields.Many2one(comodel_name="test_trade.order.line")

    # ROUTING

    _direction = SALE

    # ─── Hooks consumed by later tasks (trivial stubs) ─────────────

    def _get_default_line_description(self):
        return self.product_id.display_name or "/"

    def _get_auto_price_and_discount(self):
        self.check_singleton()
        return (self.product_id.list_price, 0.0)

    def _is_price_update_blocked(self):
        return False

    def _get_fields_tracked_qty(self):
        return ["product_qty"]

    def _post_quantity_changes(self, field_name, changes):
        for change in changes:
            change["line"].order_id.message_post(
                body=f"{field_name}: {change['old_qty']} -> {change['new_qty']}"
            )

    def _get_catalog_single_line_data(self, **kwargs):
        return {
            "quantity": self.product_qty,
            "price": self.price_unit,
            "readOnly": self.order_id._is_readonly(),
        }

    def _get_catalog_multi_line_data(self, **kwargs):
        return {"price": self.price_unit}
