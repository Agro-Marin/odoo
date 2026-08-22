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
    for table, model in [
        ("mrp_workorder", "mrp.workorder"),
        ("mrp_production", "mrp.production"),
    ]:
        if not _column_exists(cr, table, "date_finished"):
            continue

        if _column_exists(cr, table, "date_end"):
            cr.execute(f"""
                UPDATE {table}
                   SET date_end = date_finished
                 WHERE date_finished IS NOT NULL
            """)
            cr.execute(f"ALTER TABLE {table} DROP COLUMN date_finished")
        else:
            cr.execute(f"ALTER TABLE {table} RENAME COLUMN date_finished TO date_end")

        cr.execute(
            """
            DELETE FROM ir_model_fields
             WHERE model = %s AND name = 'date_finished'
        """,
            [model],
        )

    cr.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename IN ('mrp_workorder', 'mrp_production')
          AND indexname LIKE '%%date_finished%%'
    """)
    for (idx_name,) in cr.fetchall():
        cr.execute(f'DROP INDEX IF EXISTS "{idx_name}"')
