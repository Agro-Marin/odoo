from odoo import fields, models
from odoo.osv import expression


class ProductProduct(models.Model):
    "Inherit ProductProduct"

    _inherit = "product.product"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # used to compute quantities
    purchase_order_line_ids = fields.One2many(
        comodel_name="purchase.order.line",
        inverse_name="product_id",
        string="PO Lines",
    )

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _get_lines_domain(self, location_ids=False, warehouse_ids=False):
        domains = []
        rfq_domain = [
            ("state", "=", "draft"),
            ("product_id", "in", self.ids),
        ]
        if location_ids:
            domains.append(
                expression.AND(
                    [
                        rfq_domain,
                        [
                            "|",
                            "|",
                            (
                                "order_id.picking_type_id.default_location_dest_id",
                                "in",
                                location_ids,
                            ),
                            "&",
                            ("move_ids", "=", False),
                            ("location_final_id", "child_of", location_ids),
                            "&",
                            ("move_dest_ids", "=", False),
                            ("orderpoint_id.location_id", "in", location_ids),
                        ],
                    ]
                )
            )
        if warehouse_ids:
            domains.append(
                expression.AND(
                    [
                        rfq_domain,
                        [
                            "|",
                            (
                                "order_id.picking_type_id.warehouse_id",
                                "in",
                                warehouse_ids,
                            ),
                            "&",
                            ("move_dest_ids", "=", False),
                            ("orderpoint_id.warehouse_id", "in", warehouse_ids),
                        ],
                    ]
                )
            )
        return expression.OR(domains) if domains else []

    def _get_quantity_in_progress(self, location_ids=False, warehouse_ids=False):
        if not location_ids:
            location_ids = []
        if not warehouse_ids:
            warehouse_ids = []

        qty_by_product_location, qty_by_product_wh = super()._get_quantity_in_progress(
            location_ids, warehouse_ids
        )
        domain = self._get_lines_domain(location_ids, warehouse_ids)
        groups = (
            self.env["purchase.order.line"]
            .sudo()
            ._read_group(
                domain,
                [
                    "order_id",
                    "product_id",
                    "product_uom_id",
                    "orderpoint_id",
                    "location_final_id",
                ],
                ["product_qty:sum"],
            )
        )
        for order, product, uom, orderpoint, location_final, product_qty_sum in groups:
            if orderpoint:
                location = orderpoint.location_id
            elif location_final:
                location = location_final
            else:
                location = order.picking_type_id.default_location_dest_id
            product_qty = uom._compute_quantity(
                product_qty_sum, product.uom_id, round=False
            )
            qty_by_product_location[(product.id, location.id)] += product_qty
            qty_by_product_wh[(product.id, location.warehouse_id.id)] += product_qty
        return qty_by_product_location, qty_by_product_wh
