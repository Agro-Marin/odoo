from odoo.db.schema import column_exists

MAX_CYCLIC_INVENTORY_DAYS = 36500


def migrate(cr, version):
    if not version:
        return

    if column_exists(cr, "stock_location", "cyclic_inventory_frequency"):
        cr.execute(
            """
            UPDATE stock_location
               SET cyclic_inventory_frequency = %s
             WHERE cyclic_inventory_frequency > %s
            """,
            (MAX_CYCLIC_INVENTORY_DAYS, MAX_CYCLIC_INVENTORY_DAYS),
        )

    if column_exists(cr, "stock_location", "barcode"):
        cr.execute(
            """
            UPDATE stock_location
               SET barcode = NULL
             WHERE company_id IS NULL
               AND barcode IS NOT NULL
               AND id NOT IN (
                     SELECT min(id)
                       FROM stock_location
                      WHERE company_id IS NULL
                        AND barcode IS NOT NULL
                   GROUP BY barcode
                   )
            """
        )
        cr.execute(
            """
            ALTER TABLE stock_location
            DROP CONSTRAINT IF EXISTS stock_location_barcode_company_uniq
            """
        )
        cr.execute(
            """
            DELETE FROM ir_model_constraint
             WHERE name = 'stock_location_barcode_company_uniq'
            """
        )
