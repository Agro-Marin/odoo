def _column_exists(cr, table, column) -> bool:
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version) -> None:
    if not version:
        return

    # move_dest_id was written by no code in any repository, so the column is
    # empty everywhere and the One2many it backed on stock.move could never
    # resolve. Dropped rather than populated: the procurement path that used to
    # set it (a stock rule creating an agreement instead of a purchase order)
    # does not exist in 19.0.
    if _column_exists(cr, "purchase_requisition_line", "move_dest_id"):
        cr.execute('ALTER TABLE purchase_requisition_line DROP COLUMN "move_dest_id"')
