from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    purchase_line_ids = fields.Many2many(
        comodel_name="purchase.order.line",
        relation="account_move_line_purchase_order_line_rel",
        column1="move_line_id",
        column2="order_line_id",
        string="Purchase Order Lines",
        copy=False,
    )
    purchase_line_warn_msg = fields.Text(
        compute="_compute_purchase_line_warn_msg",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("product_id.purchase_line_warn_msg")
    def _compute_purchase_line_warn_msg(self):
        self._compute_warn_msg_from_product(
            "purchase_line_warn_msg",
            "purchase.group_warning_purchase",
        )

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_order_line_link_fields(self):
        return [*super()._get_order_line_link_fields(), "purchase_line_ids"]

    def _purchase_prepare_purchase_line_values(self):
        """Build creation values for ``purchase.order.line`` records from invoice lines.

        Used by the "Create Purchase Order from Bill" wizard to seed PO lines with
        the product, quantity, UoM, price and discount of the originating bill lines.

        :return: One dict of creation values per record in ``self``.
        :rtype: list[dict]
        """
        return [
            {
                "product_id": line.product_id.id,
                "product_qty": line.quantity,
                "product_uom_id": line.product_uom_id.id,
                "price_unit": line.price_unit,
                "discount": line.discount,
            }
            for line in self
        ]

    # _copy_data_extend_business_fields and _related_analytic_distribution are
    # inherited from base_order; both act on _get_order_line_link_fields above.
