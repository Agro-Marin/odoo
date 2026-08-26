from odoo import Command, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _pre_action_done_hook(self):
        res = super()._pre_action_done_hook()
        if res is True and not self.env.context.get("skip_expired"):
            expired_lines = self._expired_move_lines()
            if expired_lines:
                return expired_lines.picking_id._action_generate_expired_wizard(
                    expired_lines
                )
        return res

    def _expired_move_lines(self):
        return self.move_line_ids._filtered_expired()

    def _check_expired_lots(self):
        return self._expired_move_lines().picking_id

    def _action_generate_expired_wizard(self, expired_lines=None):
        if expired_lines is None:
            expired_lines = self._expired_move_lines()
        view_id = self.env.ref("product_expiry.confirm_expiry_view").id
        context = dict(self.env.context)
        context.update(
            {
                "default_picking_ids": [Command.set(self.ids)],
                "default_lot_ids": [Command.set(expired_lines.lot_id.ids)],
            }
        )
        return {
            "name": self.env._("Confirmation"),
            "type": "ir.actions.act_window",
            "res_model": "expiry.picking.confirmation",
            "view_mode": "form",
            "views": [(view_id, "form")],
            "view_id": view_id,
            "target": "new",
            "context": context,
        }
