from odoo import fields, models
from odoo.tools import SQL


class PurchaseReport(models.Model):
    _inherit = "purchase.report"

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

    def _select(self) -> SQL:
        return SQL(
            """
            %s,
            spt.warehouse_id AS picking_type_id,
            o.date_effective AS date_effective,
            EXTRACT(
                epoch from age(
                    l.date_planned,
                    COALESCE(
                        order_date_effective.date_done,
                        o.date_order
                    )
                )
            ) / (24*60*60)::decimal(16,2) AS days_to_arrival
            """,
            super()._select(),
        )

    def _from(self) -> SQL:
        return SQL(
            """
            %s
            LEFT JOIN stock_picking_type spt
                ON o.picking_type_id = spt.id
            LEFT JOIN (
                SELECT
                    MIN(picking.date_done) AS date_done,
                    purchase.id AS purchase_id
                FROM
                    purchase_order purchase
                JOIN purchase_order_line order_line
                    ON purchase.id = order_line.order_id
                    JOIN stock_move move
                        ON order_line.id = move.purchase_line_id
                    JOIN stock_picking picking
                        ON move.picking_id = picking.id
                JOIN stock_location location_dest
                    ON picking.location_dest_id = location_dest.id
                WHERE
                    picking.state = 'done'
                    AND location_dest.usage != 'supplier'
                    AND picking.date_done IS NOT NULL
                GROUP BY
                    purchase.id
            ) order_date_effective
                ON l.order_id = order_date_effective.purchase_id
            """,
            super()._from(),
        )

    def _group_by(self) -> SQL:
        return SQL(
            "%s, spt.warehouse_id, date_effective, order_date_effective.date_done",
            super()._group_by(),
        )
