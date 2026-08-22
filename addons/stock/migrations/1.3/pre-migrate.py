from odoo.db.schema import column_exists


def migrate(cr, version):
    if not version:
        return

    if column_exists(cr, "stock_move", "product_uom") and not column_exists(
        cr, "stock_move", "product_uom_id"
    ):
        cr.execute(
            'ALTER TABLE "stock_move" RENAME COLUMN "product_uom" TO "product_uom_id"'
        )

    cr.execute(
        r"""
        UPDATE ir_ui_view
           SET arch_db = regexp_replace(
                   arch_db::text, '\yproduct_uom\y', 'product_uom_id', 'g')::jsonb
         WHERE arch_db::text ~ '\yproduct_uom\y'
        """
    )

    cr.execute(
        r"""
        UPDATE ir_filters
           SET domain = regexp_replace(domain, '\yproduct_uom\y', 'product_uom_id', 'g'),
               context = regexp_replace(context, '\yproduct_uom\y', 'product_uom_id', 'g')
         WHERE (domain ~ '\yproduct_uom\y' OR context ~ '\yproduct_uom\y')
           AND model_id = 'stock.move'
        """
    )
    cr.execute(
        """
        UPDATE ir_exports_line l
           SET name = 'product_uom_id'
          FROM ir_exports e
         WHERE l.export_id = e.id
           AND e.resource = 'stock.move'
           AND l.name = 'product_uom'
        """
    )
