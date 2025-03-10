from odoo import api, fields, models


class StockPicking(models.Model):
    "Inherit StockPicking"

    _inherit = "stock.picking"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    purchase_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Orders",
        readonly=True,
        index="btree_not_null",
    )
    delay_pass = fields.Datetime(
        compute="_compute_date_order",
        search="_search_delay_pass",
        copy=False,
        index=True,
    )
    days_to_arrive = fields.Datetime(
        compute="_compute_days_to_arrive",
        search="_search_days_to_arrive",
        copy=False,
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_date_order(self):
        for picking in self:
            picking.delay_pass = (
                picking.purchase_id.date_order
                if picking.purchase_id
                else fields.Datetime.now()
            )

    @api.depends("state", "location_dest_id.usage", "date_done")
    def _compute_days_to_arrive(self):
        for picking in self:
            if (
                picking.state == "done"
                and picking.location_dest_id.usage != "supplier"
                and picking.date_done
            ):
                picking.days_to_arrive = picking.date_done
            else:
                picking.days_to_arrive = False

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    @api.model
    def _search_days_to_arrive(self, operator, value):
        date_value = fields.Datetime.from_string(value)
        return [("date_done", operator, date_value)]

    @api.model
    def _search_delay_pass(self, operator, value):
        date_value = fields.Datetime.from_string(value)
        return [("purchase_id.date_order", operator, date_value)]
