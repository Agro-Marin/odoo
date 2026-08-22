from odoo.db.schema import column_exists


def migrate(cr, version):
    if not version:
        return

    if column_exists(cr, "stock_move", "packaging_uom_id"):
        cr.execute(
            r"""
            UPDATE stock_move sm
               SET packaging_uom_id     = sm.product_uom_id,
                   quantity_packaging_uom = sm.product_uom_qty
              FROM uom_uom pu, uom_uom ku
             WHERE pu.id = sm.product_uom_id
               AND ku.id = sm.packaging_uom_id
               AND sm.packaging_uom_id IS NOT NULL
               AND sm.packaging_uom_id <> sm.product_uom_id
               AND split_part(pu.parent_path, '/', 1)
                     <> split_part(ku.parent_path, '/', 1)
            """
        )

    if column_exists(cr, "stock_warehouse_orderpoint", "replenishment_uom_id"):
        cr.execute(
            r"""
            UPDATE stock_warehouse_orderpoint op
               SET replenishment_uom_id = NULL
              FROM product_product pp
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              JOIN uom_uom pu ON pu.id = pt.uom_id,
                   uom_uom ru
             WHERE pp.id = op.product_id
               AND ru.id = op.replenishment_uom_id
               AND op.replenishment_uom_id IS NOT NULL
               AND split_part(pu.parent_path, '/', 1)
                     <> split_part(ru.parent_path, '/', 1)
            """
        )
