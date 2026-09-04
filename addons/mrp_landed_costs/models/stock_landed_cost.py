from odoo import api, fields, models


class StockLandedCost(models.Model):
    _inherit = "stock.landed.cost"

    target_model = fields.Selection(
        selection_add=[("manufacturing", "Manufacturing Orders")],
        ondelete={"manufacturing": "set default"},
    )
    mrp_production_ids = fields.Many2many(
        "mrp.production",
        string="Manufacturing order",
        copy=False,
        groups="stock.group_stock_manager",
    )
    mrp_production_count = fields.Integer(
        string="Count of Manufacturing Orders",
        compute="_compute_mrp_production_count",
        groups="stock.group_stock_manager",
    )

    @api.depends("mrp_production_ids")
    def _compute_mrp_production_count(self):
        for cost in self:
            cost.mrp_production_count = len(cost.mrp_production_ids)

    @api.onchange("target_model")
    def _onchange_target_model(self):
        super()._onchange_target_model()
        if self.target_model != "manufacturing":
            self.mrp_production_ids = False

    def action_view_mrp_productions(self):
        self.check_singleton()
        action = {
            "type": "ir.actions.act_window",
            "res_model": "mrp.production",
        }
        if len(self.mrp_production_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.mrp_production_ids.id,
                }
            )
        else:
            action.update(
                {
                    "name": self.env._("Manufacturing Orders of %s", self.name),
                    "view_mode": "list,form",
                    "domain": [("id", "in", self.mrp_production_ids.ids)],
                }
            )
        return action

    def _get_targeted_move_ids(self):
        return (
            super()._get_targeted_move_ids()
            | self.mrp_production_ids.move_finished_ids
            - self.mrp_production_ids.move_byproduct_ids.filtered(
                lambda move: not move.cost_share
            )
        )
