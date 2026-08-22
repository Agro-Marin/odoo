from odoo.db.schema import column_exists


def migrate(cr, version):
    if not column_exists(cr, "stock_warehouse_orderpoint", "qty_to_order_manual_zero"):
        return
    if not column_exists(cr, "stock_warehouse_orderpoint", "qty_to_order_manual_set"):
        cr.execute(
            """
            ALTER TABLE stock_warehouse_orderpoint
            RENAME COLUMN qty_to_order_manual_zero TO qty_to_order_manual_set
            """,
        )
    cr.execute(
        """
        UPDATE stock_warehouse_orderpoint
           SET qty_to_order_manual_set = TRUE
         WHERE COALESCE(qty_to_order_manual_set, FALSE) IS FALSE
           AND COALESCE(qty_to_order_manual, 0) != 0
        """,
    )
