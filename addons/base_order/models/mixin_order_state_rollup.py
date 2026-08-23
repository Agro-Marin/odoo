from odoo import models

STATE_NOTHING = "no"
STATE_TODO = "to do"
STATE_PARTIAL = "partial"
STATE_DONE = "done"
STATE_OVER_DONE = "over done"


class MixinOrderStateRollup(models.AbstractModel):
    _name = "mixin.order.state.rollup"
    _description = "Order Line State Rollup"

    def _get_rollup_lines_domain(self):
        return [
            ("is_downpayment", "=", False),
            ("display_type", "=", False),
        ]

    def _rollup_line_states(self, state_field, nothing_may_be_pending=False):
        lines_domain = self._get_rollup_lines_domain()
        lines = self.env[self._get_line_model()]

        states_per_order = {}
        for order, state in lines._read_group(
            lines_domain + [("order_id", "in", self._origin.ids)],
            ["order_id", state_field],
        ):
            states_per_order.setdefault(order.id, set()).add(state)

        ambiguous_ids = [
            order._origin.id
            for order in self
            if nothing_may_be_pending
            and STATE_NOTHING in states_per_order.get(order._origin.id, set())
        ]
        pending_ids = set()
        if ambiguous_ids:
            pending_ids = {
                order.id
                for (order,) in lines._read_group(
                    lines_domain
                    + [
                        ("order_id", "in", ambiguous_ids),
                        (state_field, "=", STATE_NOTHING),
                        ("product_qty", "!=", 0),
                    ],
                    ["order_id"],
                )
            }
        return states_per_order, pending_ids
