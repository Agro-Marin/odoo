from odoo import Command, _, api, fields, models
from odoo.db.schema import column_exists, create_column
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    sale_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        compute="_compute_sale_id",
        store=True,
        inverse="_inverse_sale_id",
        index="btree_not_null",
    )
    days_to_deliver = fields.Datetime(
        compute="_compute_days_to_deliver",
        search="_search_days_to_deliver",
        copy=False,
    )

    def _auto_init(self):
        if not column_exists(self.env.cr, "stock_picking", "sale_id"):
            create_column(self.env.cr, "stock_picking", "sale_id", "int4")
        return super()._auto_init()

    @api.depends(
        "reference_ids.sale_ids",
        "move_ids.sale_line_id.order_id",
    )
    def _compute_sale_id(self):
        for picking in self:
            sale_order = picking.move_ids.sale_line_id.order_id[:1]
            if not sale_order and not picking._is_on_manufacturing_route():
                sale_order = picking.reference_ids.sale_ids[:1]
            picking.sale_id = sale_order

    @api.depends("move_ids.sale_line_id.order_id.picking_policy")
    def _compute_move_type(self):
        super()._compute_move_type()
        for picking in self:
            sale_orders = picking.move_ids.sale_line_id.order_id
            if sale_orders:
                if any(so.picking_policy == "direct" for so in sale_orders):
                    picking.move_type = "direct"
                else:
                    picking.move_type = "one"

    def _days_to_deliver_domain(self):
        return self._effective_transfer_domain() & Domain(
            "location_dest_id.usage",
            "=",
            "customer",
        )

    @api.depends("state", "location_dest_id.usage", "date_done")
    def _compute_days_to_deliver(self):
        self._compute_effective_transfer_date(
            "days_to_deliver",
            self._days_to_deliver_domain(),
        )

    def _get_source_order_date(self):
        return self.sale_id.date_order or super()._get_source_order_date()

    def _is_on_manufacturing_route(self):
        self.check_singleton()
        return False

    def _inverse_sale_id(self):
        if self.reference_ids:
            if self.sale_id:
                self.reference_ids.sudo().sale_ids = [Command.link(self.sale_id.id)]
            else:
                sale_order = self.move_ids.sale_line_id.order_id
                if len(sale_order) == 1:
                    self.reference_ids.sudo().sale_ids = [Command.unlink(sale_order.id)]
        elif self.sale_id:
            reference = (
                self.env["stock.reference"]
                .sudo()
                .create(
                    {
                        "sale_ids": [Command.link(self.sale_id.id)],
                        "name": self.sale_id.name,
                    },
                )
            )
            self._add_reference(reference)
        self.move_ids._reassign_sale_lines(self.sale_id)

    @api.model
    def _search_days_to_deliver(self, operator, value):
        return self._search_effective_transfer_date(
            operator,
            value,
            self._days_to_deliver_domain(),
        )

    @api.model
    def _get_source_order_date_paths(self):
        return [*super()._get_source_order_date_paths(), "sale_id.date_order"]

    def _log_less_quantities_than_expected(self, moves):
        def _keys_in_groupby(sale_line):
            return (sale_line.order_id, sale_line.order_id.user_id)

        def _render_note_exception_quantity(moves_information):
            origin_moves = self.env["stock.move"].browse(
                [
                    move.id
                    for move_orig in moves_information.values()
                    for move in move_orig[0]
                ],
            )
            origin_picking = origin_moves.mapped("picking_id")
            values = {
                "origin_moves": origin_moves,
                "origin_picking": origin_picking,
                "moves_information": moves_information.values(),
            }
            return self.env["ir.qweb"]._render(
                "sale_stock.exception_on_picking", values
            )

        documents = self.sudo()._log_activity_get_documents(
            moves, "sale_line_id", "DOWN", _keys_in_groupby
        )
        self._log_activity(_render_note_exception_quantity, documents)

        return super()._log_less_quantities_than_expected(moves)

    def action_sale_matching(self):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sales Matching"),
            "res_model": "sale.delivery.line.match",
            "views": [
                (self.env.ref("sale_stock.sale_delivery_line_match_list").id, "list"),
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
