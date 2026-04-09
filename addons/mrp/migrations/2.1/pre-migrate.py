"""Pre-migration: rename date_finished → date_end on mrp models.

Aligns mrp.workorder and mrp.production with resource.scheduling.mixin
field naming convention.  If date_end already exists (from mixin), copies
data from date_finished and drops the old column.
"""


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, [table, column])
    return bool(cr.fetchone())


def migrate(cr, version):
    for table, model in [
        ("mrp_workorder", "mrp.workorder"),
        ("mrp_production", "mrp.production"),
    ]:
        if not _column_exists(cr, table, "date_finished"):
            continue

        if _column_exists(cr, table, "date_end"):
            # date_end was created by mixin — copy data, drop old column
            cr.execute(f"""
                UPDATE {table}
                   SET date_end = date_finished
                 WHERE date_finished IS NOT NULL
            """)
            cr.execute(f"ALTER TABLE {table} DROP COLUMN date_finished")
        else:
            cr.execute(f"ALTER TABLE {table} RENAME COLUMN date_finished TO date_end")

        # Delete stale field record — ORM will recreate with correct definition
        cr.execute("""
            DELETE FROM ir_model_fields
             WHERE model = %s AND name = 'date_finished'
        """, [model])

    # Drop old indexes — ORM recreates them on update
    cr.execute("""
        DO $$
        DECLARE
            idx RECORD;
        BEGIN
            FOR idx IN
                SELECT indexname, tablename FROM pg_indexes
                WHERE tablename IN ('mrp_workorder', 'mrp_production')
                  AND indexname LIKE '%%date_finished%%'
            LOOP
                EXECUTE format('DROP INDEX IF EXISTS %%I', idx.indexname);
            END LOOP;
        END $$;
    """)
