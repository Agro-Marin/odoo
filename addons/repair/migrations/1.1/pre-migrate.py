r"""Pre-migration for the ``repair.order.product_uom`` -> ``product_uom_id`` rename.

The stored ``Many2one`` field ``product_uom`` (unit of measure of the repair
order) was renamed to ``product_uom_id`` to match the fork-wide ``*_id``
convention. This renames the real column on ``repair_order`` *before* the ORM
loads the new model definition, so the populated data is preserved instead of the
ORM creating an empty ``product_uom_id`` column and dropping ``product_uom``.

It also rewrites the whole-word ``product_uom`` token in stored view arch and in
user-created ``ir.filters`` / ``ir.exports.line`` for ``repair.order`` so
revalidation against the new model passes. ``\y`` (Postgres word boundary) leaves
lookalikes such as ``product_uom_qty`` untouched.
"""

from odoo.tools.sql import column_exists


def migrate(cr, version):
    """Rename the column and refresh stored references to the old field name.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: the ORM creates product_uom_id directly

    if column_exists(cr, "repair_order", "product_uom") and not column_exists(
        cr, "repair_order", "product_uom_id"
    ):
        cr.execute(
            'ALTER TABLE "repair_order" RENAME COLUMN "product_uom" TO "product_uom_id"'
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
           AND model_id = 'repair.order'
        """
    )
    cr.execute(
        """
        UPDATE ir_exports_line l
           SET name = 'product_uom_id'
          FROM ir_exports e
         WHERE l.export_id = e.id
           AND e.resource = 'repair.order'
           AND l.name = 'product_uom'
        """
    )
