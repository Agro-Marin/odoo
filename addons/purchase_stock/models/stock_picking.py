from odoo import _, api, fields, models
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    purchase_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        compute="_compute_purchase_id",
        store=True,
        index="btree_not_null",
    )
    days_to_arrive = fields.Datetime(
        compute="_compute_days_to_arrive",
        search="_search_days_to_arrive",
        copy=False,
    )

    def _get_fields_linking_orders(self):
        return ["purchase_id", *super()._get_fields_linking_orders()]

    @api.depends("move_ids.purchase_line_id.order_id")
    def _compute_purchase_id(self):
        for picking in self:
            picking.purchase_id = picking.move_ids.purchase_line_id.order_id

    def _days_to_arrive_domain(self):
        return self._effective_transfer_domain() & Domain(
            "location_dest_id.usage",
            "!=",
            "supplier",
        )

    @api.depends("state", "location_dest_id.usage", "date_done")
    def _compute_days_to_arrive(self):
        self._compute_effective_transfer_date(
            "days_to_arrive",
            self._days_to_arrive_domain(),
        )

    @api.model
    def _search_days_to_arrive(self, operator, value):
        return self._search_effective_transfer_date(
            operator,
            value,
            self._days_to_arrive_domain(),
        )

    def _action_done(self):
        self.purchase_id.sudo().action_acknowledge()
        return super()._action_done()

    def action_purchase_matching(self):
        return self._get_action_transfer_matching(
            _("Purchase Matching"),
            "purchase.receipt.line.match",
            "purchase_stock.purchase_receipt_line_match_list",
        )
