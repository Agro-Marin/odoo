import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    "Inherit SaleOrder"

    _inherit = "sale.order"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        compute="_compute_warehouse_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
    )
    procurement_group_id = fields.Many2one(
        comodel_name="procurement.group",
        string="Procurement Group",
        copy=False,
    )
    incoterm_id = fields.Many2one(
        comodel_name="account.incoterms",
        string="Incoterm",
        help="International Commercial Terms are a series of predefined commercial terms used in international transactions.",
    )
    incoterm_location = fields.Char(string="Incoterm Location")
    picking_policy = fields.Selection(
        selection=[
            ("direct", "As soon as possible"),
            ("one", "When all products are ready"),
        ],
        string="Shipping Policy",
        required=True,
        default="direct",
        help="If you deliver all products at once, the delivery order will be scheduled based on the greatest "
        "product lead time. Otherwise, it will be based on the shortest.",
    )
    picking_ids = fields.One2many(
        comodel_name="stock.picking",
        inverse_name="sale_id",
        string="Transfers",
        copy=False,
    )
    count_picking_ids = fields.Integer(
        string="Delivery Orders",
        compute="_compute_count_picking_ids",
    )
    transfer_state = fields.Selection(
        selection=[
            ("no", "Nothing to transfer"),
            ("to do", "To transfer"),
            ("partially", "Partially transferred"),
            ("done", "Fully transferred"),
            ("over done", "Over transferred"),
        ],
        string="Delivery Status",
        compute="_compute_transfer_state",
        store=True,
        help="Blue: Not Delivered/Started\n\
            Orange: Partially Delivered\n\
            Green: Fully Delivered",
    )
    date_planned = fields.Datetime(
        help="Delivery date you can promise to the customer, computed from the minimum lead time of "
        "the order lines in case of Service products. In case of shipping, the shipping policy of "
        "the order will be taken into account to either use the minimum or maximum lead time of "
        "the order lines."
    )
    date_effective = fields.Datetime(
        string="Effective Date",
        compute="_compute_date_effective",
        store=True,
        help="Completion date of the first delivery order.",
    )
    show_json_popover = fields.Boolean(
        string="Has late picking",
        compute="_compute_json_popover",
    )
    json_popover = fields.Char(
        string="JSON data for the popover widget",
        compute="_compute_json_popover",
    )

    # ------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------

    def _init_column(self, column_name):
        """Ensure the default warehouse_id is correctly assigned

        At column initialization, the ir.model.fields for res.users.property_warehouse_id isn't created,
        which means trying to read the property field to get the default value will crash.
        We therefore enforce the default here, without going through
        the default function on the warehouse_id field.
        """
        if column_name != "warehouse_id":
            return super()._init_column(column_name)

        default_warehouse = self.env["stock.warehouse"].search([], limit=1)

        query = """
        UPDATE sale_order so
        SET warehouse_id = COALESCE(wh.id, %s)
        FROM stock_warehouse wh
        WHERE so.company_id = wh.company_id and so.warehouse_id IS NULL and wh.activeAdd commentMore actions
        """
        params = [default_warehouse.id]

        _logger.debug(
            "Initializing column '%s' in table '%s'", column_name, self._table
        )
        self._cr.execute(query, params)

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

    @api.constrains("warehouse_id", "state", "line_ids")
    def _check_warehouse(self):
        """Ensure that the warehouse is set in case of storable products"""
        orders_without_wh = self.filtered(
            lambda order: order.state not in ("draft", "cancel")
            and not order.warehouse_id
        )
        company_ids_with_wh = {
            company_id.id
            for [company_id] in self.env["stock.warehouse"]._read_group(
                domain=[("company_id", "in", orders_without_wh.company_id.ids)],
                groupby=["company_id"],
            )
        }
        other_company = set()
        for order_line in orders_without_wh.line_ids:
            if order_line.product_id.type != "consu":
                continue

            if (
                order_line.route_id.company_id
                and order_line.route_id.company_id != order_line.company_id
            ):
                other_company.add(order_line.route_id.company_id.id)
                continue

            if order_line.order_id.company_id.id in company_ids_with_wh:
                raise UserError(
                    _("You must set a warehouse on your sale order to proceed.")
                )

            self.env["stock.warehouse"].with_company(
                order_line.order_id.company_id
            )._warehouse_redirect_warning()
        other_company_warehouses = self.env["stock.warehouse"].search(
            [("company_id", "in", list(other_company))]
        )
        if any(c not in other_company_warehouses.company_id.ids for c in other_company):
            raise UserError(
                _(
                    "You must have a warehouse for line using a delivery in different company."
                )
            )

    # --------------------------------------------------
    # CRUD METHODS
    # --------------------------------------------------

    def write(self, vals):
        if vals.get("line_ids") and self.state == "sale":
            for order in self:
                pre_order_line_qty = {
                    order_line: order_line.product_uom_qty
                    for order_line in order.mapped("line_ids")
                    if not order_line.is_expense
                }

        if vals.get("partner_shipping_id"):
            if self._context.get("update_delivery_shipping_partner"):
                for order in self:
                    order.picking_ids.partner_id = vals.get("partner_shipping_id")
            else:
                new_partner = self.env["res.partner"].browse(
                    vals.get("partner_shipping_id")
                )
                for order in self:
                    picking = order.mapped("picking_ids").filtered(
                        lambda x: x.state not in ("done", "cancel")
                    )
                    message = _(
                        """The delivery address has been changed on the Sales Order<br/>
                            From <strong>"%(old_address)s"</strong> to <strong>"%(new_address)s"</strong>,
                            You should probably update the partner on this document.""",
                        old_address=order.partner_shipping_id.display_name,
                        new_address=new_partner.display_name,
                    )
                    picking.activity_schedule(
                        "mail.mail_activity_data_warning",
                        note=message,
                        user_id=self.env.user.id,
                    )

        if "date_commitment" in vals:
            # protagate date_commitment as the deadline of the related stock move.
            # TODO: Log a note on each down document
            deadline_datetime = vals.get("date_commitment")
            for order in self:
                order.line_ids.move_ids.date_deadline = (
                    deadline_datetime or order.date_planned
                )

        res = super().write(vals)

        if vals.get("line_ids") and self.state == "sale":
            for order in self:
                to_log = {}
                order.line_ids.fetch(
                    [
                        "product_uom_id",
                        "product_uom_qty",
                        "display_type",
                        "is_downpayment",
                    ]
                )
                for order_line in order.line_ids:
                    if order_line.display_type or order_line.is_downpayment:
                        continue

                    if (
                        float_compare(
                            order_line.product_uom_qty,
                            pre_order_line_qty.get(order_line, 0.0),
                            precision_rounding=order_line.product_uom_id.rounding,
                        )
                        < 0
                    ):
                        to_log[order_line] = (
                            order_line.product_uom_qty,
                            pre_order_line_qty.get(order_line, 0.0),
                        )
                if to_log:
                    documents = (
                        self.env["stock.picking"]
                        .sudo()
                        ._log_activity_get_documents(to_log, "move_ids", "UP")
                    )
                    documents = {
                        k: v for k, v in documents.items() if k[0].state != "cancel"
                    }
                    order._log_decrease_ordered_quantity(documents)
        return res

    # --------------------------------------------------
    # COMPUTE METHODS
    # --------------------------------------------------

    @api.depends("company_id", "user_id")
    def _compute_warehouse_id(self):
        for order in self:
            default_warehouse_id = (
                self.env["ir.default"]
                .with_company(order.company_id.id)
                ._get_model_defaults("sale.order")
                .get("warehouse_id")
            )
            if order.state == "draft" or not order.ids:
                # Should expect empty
                if default_warehouse_id is not None:
                    order.warehouse_id = default_warehouse_id
                else:
                    order.warehouse_id = order.user_id.with_company(
                        order.company_id.id
                    )._get_default_warehouse_id()

    @api.depends("picking_policy")
    def _compute_date_planned(self):
        super()._compute_date_planned()

    @api.depends("picking_ids")
    def _compute_count_picking_ids(self):
        for order in self:
            order.count_picking_ids = len(order.picking_ids)

    @api.depends("picking_ids.date_done")
    def _compute_date_effective(self):
        for order in self:
            pickings = order.picking_ids.filtered(
                lambda x: x.state == "done"
                and x.location_dest_id.usage == "customer"
                and x.date_done
            )
            order.date_effective = min(pickings.mapped("date_done"), default=False)

    @api.depends("picking_ids", "picking_ids.state")
    def _compute_json_popover(self):
        for order in self:
            late_stock_picking = order.picking_ids.filtered(
                lambda p: p.date_delay_alert
            )
            order.json_popover = json.dumps(
                {
                    "popoverTemplate": "sale_stock.DelayAlertWidget",
                    "late_elements": [
                        {
                            "id": late_move.id,
                            "name": late_move.display_name,
                            "model": "stock.picking",
                        }
                        for late_move in late_stock_picking
                    ],
                }
            )
            order.show_json_popover = bool(late_stock_picking)

    @api.depends("line_ids.qty_transfered", "picking_ids", "picking_ids.state")
    def _compute_transfer_state(self):
        for order in self:
            transfer_state = "to do"
            if not order.picking_ids or all(
                p.state == "cancel" for p in order.picking_ids
            ):
                transfer_state = "no"
            elif all(p.state in ["done", "cancel"] for p in order.picking_ids):
                transfer_state = "done"
            elif any(p.state == "done" for p in order.picking_ids) and any(
                l.qty_transfered for l in order.order_line
            ):
                transfer_state = "partially"
            order.transfer_state = transfer_state

    # --------------------------------------------------
    # ONCHANGE METHODS
    # --------------------------------------------------

    @api.onchange("partner_shipping_id")
    def _onchange_partner_shipping_id(self):
        res = {}
        pickings = self.picking_ids.filtered(
            lambda p: p.state not in ["done", "cancel"]
            and p.partner_id != self.partner_shipping_id
        )
        if pickings:
            res["warning"] = {
                "title": _("Warning!"),
                "message": _(
                    "Do not forget to change the partner on the following delivery orders: %s",
                    ",".join(pickings.mapped("name")),
                ),
            }
        return res

    # --------------------------------------------------
    # ACTIONS
    # --------------------------------------------------

    def action_view_picking(self):
        return self._get_action_view_picking(self.picking_ids)

    def action_cancel(self):
        documents = None
        for sale_order in self:
            if sale_order.state == "sale" and sale_order.line_ids:
                sale_order_lines_quantities = {
                    order_line: (order_line.product_uom_qty, 0)
                    for order_line in sale_order.line_ids
                }
                documents = (
                    self.env["stock.picking"]
                    .with_context(include_draft_documents=True)
                    ._log_activity_get_documents(
                        sale_order_lines_quantities, "move_ids", "UP"
                    )
                )
        self.picking_ids.filtered(lambda p: p.state != "done").action_cancel()
        if documents:
            filtered_documents = {}
            for (parent, responsible), rendering_context in documents.items():
                if parent._name == "stock.picking":
                    if parent.state == "cancel":
                        continue

                filtered_documents[(parent, responsible)] = rendering_context
            self._log_decrease_ordered_quantity(filtered_documents, cancel=True)
        return super().action_cancel()

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _hook_action_confirm(self):
        self.line_ids._action_launch_stock_rule()
        return super()._hook_action_confirm()

    def _log_decrease_ordered_quantity(self, documents, cancel=False):

        def _render_note_exception_quantity_so(rendering_context):
            order_exceptions, visited_moves = rendering_context
            visited_moves = list(visited_moves)
            visited_moves = self.env[visited_moves[0]._name].concat(*visited_moves)
            line_ids = self.env["sale.order.line"].browse(
                [
                    order_line.id
                    for order in order_exceptions.values()
                    for order_line in order[0]
                ]
            )
            sale_order_ids = line_ids.mapped("order_id")
            impacted_pickings = visited_moves.filtered(
                lambda m: m.state not in ("done", "cancel")
            ).mapped("picking_id")
            values = {
                "sale_order_ids": sale_order_ids,
                "order_exceptions": order_exceptions.values(),
                "impacted_pickings": impacted_pickings,
                "cancel": cancel,
            }
            return self.env["ir.qweb"]._render("sale_stock.exception_on_so", values)

        self.env["stock.picking"]._log_activity(
            _render_note_exception_quantity_so, documents
        )

    def _get_action_view_picking(self, pickings):
        """This function returns an action that display existing delivery orders
        of given sales order ids. It can either be a in a list or in a form
        view, if there is only one delivery order to show."""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_picking_tree_all"
        )

        if len(pickings) > 1:
            action["domain"] = [("id", "in", pickings.ids)]
        elif pickings:
            res = self.env.ref("stock.view_picking_form", False)
            form_view = [(res and res.id or False, "form")]
            if "views" in action:
                action["views"] = form_view + [
                    (state, view) for state, view in action["views"] if view != "form"
                ]
            else:
                action["views"] = form_view
            action["res_id"] = pickings.id
        # Prepare the context.
        picking_id = pickings.filtered(lambda l: l.picking_type_id.code == "outgoing")
        if picking_id:
            picking_id = picking_id[0]
        else:
            picking_id = pickings[0]
        action["context"] = dict(
            default_partner_id=self.partner_id.id,
            default_picking_type_id=picking_id.picking_type_id.id,
            default_origin=self.name,
            default_group_id=picking_id.group_id.id,
        )
        return action

    def _get_date_planned(self, date_planneds):
        if self.picking_policy == "direct":
            return super()._get_date_planned(date_planneds)

        return max(date_planneds)

    def _prepare_invoice_vals(self):
        invoice_vals = super()._prepare_invoice_vals()
        invoice_vals["invoice_incoterm_id"] = self.incoterm_id.id
        invoice_vals["delivery_date"] = self.date_effective
        return invoice_vals
