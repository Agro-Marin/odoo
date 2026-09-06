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

    def _get_source_order_date(self):
        return self.purchase_id.date_order or super()._get_source_order_date()

    @api.model
    def _search_days_to_arrive(self, operator, value):
        return self._search_effective_transfer_date(
            operator,
            value,
            self._days_to_arrive_domain(),
        )

    @api.model
    def _get_source_order_date_paths(self):
        return [*super()._get_source_order_date_paths(), "purchase_id.date_order"]

    def _action_done(self):
        self.purchase_id.sudo().action_acknowledge()
        return super()._action_done()

    def _log_less_quantities_than_expected(self, moves):
        """Warn the buyer that the missing quantities are never coming.

        stock's own warning walks `move_dest_ids` DOWN, so it reaches whatever
        was waiting for the goods. A purchase order sits upstream of its
        receipt and is never in that set -- but it is one hop away through
        `purchase_line_id`, so no graph walk is needed here.
        """
        orders = self.move_ids.purchase_line_id.order_id
        for order in orders:
            order.sudo().activity_schedule(
                "mail.mail_activity_data_warning",
                summary=_("Missing products in receipt"),
                note=self.env["ir.qweb"]._render(
                    "purchase_stock.exception_on_receipt",
                    {
                        "origin_picking": self,
                        "moves_information": list(moves.items()),
                    },
                ),
                user_id=order.user_id.id or self.env.uid,
            )
        return super()._log_less_quantities_than_expected(moves)

    def action_purchase_matching(self):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Matching"),
            "res_model": "purchase.receipt.line.match",
            "views": [
                (
                    self.env.ref("purchase_stock.purchase_receipt_line_match_list").id,
                    "list",
                ),
            ],
            "domain": [
                ("company_id", "in", self.env.companies.ids),
                (
                    "partner_id",
                    "in",
                    (self.partner_id | self.partner_id.commercial_partner_id).ids,
                ),
                "|",
                ("picking_id", "=", self.id),
                ("picking_id", "=", False),
            ],
        }
