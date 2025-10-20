from odoo import fields, models
from odoo.tools import SQL


class PurchaseReport(models.Model):
    _inherit = "purchase.report"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    picking_type_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        readonly=True,
    )
    date_effective = fields.Datetime(string="Effective Date")
    days_to_arrival = fields.Float(
        string="Effective Days To Arrival",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
    )

    # ------------------------------------------------------------
    # QUERY METHODS
    # ------------------------------------------------------------

    def _select(self) -> SQL:
        return SQL(
            """
            %s,
            spt.warehouse_id AS picking_type_id, o.date_effective AS date_effective,
            EXTRACT(
                EPOCH FROM age(
                    l.date_planned,
                    COALESCE(
                        order_date_effective.date_done,
                        o.date_order
                    )
                )
            )/(24*60*60)::decimal(16,2) AS days_to_arrival
            """,
            super()._select(),
        )

    def _from(self) -> SQL:
        return SQL(
            """
            %s
            LEFT JOIN stock_picking_type spt ON (spt.id=o.picking_type_id)
            LEFT JOIN (
                SELECT MIN(picking.date_done)                                   AS date_done,
                    purchase.id                                                 AS purchase_id
                FROM purchase_order                                             AS purchase
                JOIN purchase_order_line                                        AS order_line
                    ON order_line.order_id = purchase.id
                JOIN stock_move                                                 AS move
                    ON move.purchase_line_id = order_line.id
                JOIN stock_picking                                              AS picking
                    ON picking.id = move.picking_id
                JOIN stock_location                                             AS location_dest
                    ON location_dest.id = picking.location_dest_id
                WHERE picking.state = 'done'
                    AND location_dest.usage != 'supplier'
                    AND picking.date_done IS NOT NULL
                GROUP BY
                    purchase.id
            ) order_date_effective
                ON order_date_effective.purchase_id = l.order_id
            """,
            super()._from(),
        )

    def _group_by(self) -> SQL:
        return SQL(
            "%s, spt.warehouse_id, date_effective, order_date_effective.date_done",
            super()._group_by(),
        )
