from odoo import api, fields, models
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    purchase_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        compute="_compute_purchase_id",
        store=True,
        index="btree_not_null",
    )
    # delay_pass is declared by base_order_stock; this module contributes the
    # purchase branch through _get_source_order_date/_get_source_order_date_paths.
    days_to_arrive = fields.Datetime(
        compute="_compute_days_to_arrive",
        search="_search_days_to_arrive",
        copy=False,
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("move_ids.purchase_line_id.order_id")
    def _compute_purchase_id(self):
        for picking in self:
            # picking and move should have a link to the SO to see the picking on the stat button.
            picking.purchase_id = picking.move_ids.purchase_line_id.order_id

    def _days_to_arrive_domain(self):
        # A purchase transfer counts unless the goods went back to the vendor.
        # Backs both the compute and the search below, so they cannot drift apart.
        return self._effective_transfer_domain() & Domain(
            "location_dest_id.usage",
            "!=",
            "supplier",
        )

    @api.depends("state", "location_dest_id.usage", "date_done")
    def _compute_days_to_arrive(self):
        # Arithmetic lives in base_order_stock; only the domain is purchase-specific.
        self._compute_effective_transfer_date(
            "days_to_arrive",
            self._days_to_arrive_domain(),
        )

    def _get_source_order_date(self):
        # Extends base_order_stock: contribute the purchase branch of delay_pass.
        return self.purchase_id.date_order or super()._get_source_order_date()

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    @api.model
    def _search_days_to_arrive(self, operator, value):
        # Mirrors _compute_days_to_arrive: without the domain this matched any
        # transfer with a date_done, deliveries and vendor returns included.
        return self._search_effective_transfer_date(
            operator,
            value,
            self._days_to_arrive_domain(),
        )

    @api.model
    def _get_source_order_date_paths(self):
        # Extends base_order_stock: contribute the purchase branch of delay_pass.
        return [*super()._get_source_order_date_paths(), "purchase_id.date_order"]

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def _action_done(self):
        self.purchase_id.sudo().action_acknowledge()
        return super()._action_done()
