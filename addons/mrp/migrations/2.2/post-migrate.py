def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _column_exists(cr, "mrp_workorder", "leave_id"):
        return
    cr.execute('ALTER TABLE "mrp_workorder" DROP COLUMN "leave_id"')
