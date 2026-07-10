r"""Pre-migration for the ``stock.move.product_uom`` -> ``product_uom_id`` rename.

The stored ``Many2one`` field ``product_uom`` (unit of measure of the move) was
renamed to ``product_uom_id`` to match the fork-wide ``*_id`` convention already
used by ``stock.move.line.product_uom_id`` and the sale/purchase lines. This
script renames the real column *before* the ORM loads the new model definition
(otherwise the ORM would create an empty ``product_uom_id`` column and drop the
populated ``product_uom`` one, losing every move's unit of measure).

It also rewrites the whole-word ``product_uom`` token to ``product_uom_id`` in
stored view arch (studio / manually customized views not restored from disk) and
in user-created ``ir.filters`` / ``ir.exports.line`` records, so revalidation of
those against the new model passes. ``\y`` (Postgres word boundary) keeps the
lookalikes ``product_uom_id`` / ``product_uom_qty`` / ``quantity_product_uom``
untouched. ``arch_db`` is jsonb (a per-language dict); the field name is never
translated and never a JSON key, so the value-level regexp is safe.
"""

from odoo.tools.sql import column_exists


def migrate(cr, version):
    """Rename the column and refresh stored references to the old field name.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: the ORM creates product_uom_id directly

    if column_exists(cr, "stock_move", "product_uom") and not column_exists(
        cr, "stock_move", "product_uom_id"
    ):
        cr.execute(
            'ALTER TABLE "stock_move" RENAME COLUMN "product_uom" TO "product_uom_id"'
        )

    # Whole-word rewrite in stored view arch (jsonb) for views not reloaded from
    # disk before validation runs.
    cr.execute(
        r"""
        UPDATE ir_ui_view
           SET arch_db = regexp_replace(
                   arch_db::text, '\yproduct_uom\y', 'product_uom_id', 'g')::jsonb
         WHERE arch_db::text ~ '\yproduct_uom\y'
        """
    )

    # User-created filters / exports that reference the old field name.
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
