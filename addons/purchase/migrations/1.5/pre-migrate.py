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
    if not version:
        return

    for table, model in [
        ("purchase_order", "purchase.order"),
        ("purchase_order_line", "purchase.order.line"),
    ]:
        if not _column_exists(cr, table, "date_planned"):
            continue

        if _column_exists(cr, table, "date_commitment"):
            cr.execute(f"""
                UPDATE {table}
                   SET date_commitment = date_planned
                 WHERE date_planned IS NOT NULL
            """)
            cr.execute(f"ALTER TABLE {table} DROP COLUMN date_planned")
        else:
            cr.execute(
                f"ALTER TABLE {table} RENAME COLUMN date_planned TO date_commitment"
            )

        cr.execute(
            """
            DELETE FROM ir_model_fields
             WHERE model = %s AND name = 'date_planned'
        """,
            [model],
        )

    cr.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename IN ('purchase_order', 'purchase_order_line')
          AND indexname LIKE '%%date_planned%%'
    """)
    for (idx_name,) in cr.fetchall():
        cr.execute(f'DROP INDEX IF EXISTS "{idx_name}"')

    cr.execute(
        """
        UPDATE mail_template
           SET body_html = REPLACE(
                   body_html::text, 'object.date_planned', 'object.date_commitment'
               )::jsonb
         WHERE body_html::text LIKE '%%object.date_planned%%'
           AND model_id IN (
               SELECT id FROM ir_model
                WHERE model IN ('purchase.order', 'purchase.order.line')
           )
    """
    )

    cr.execute(
        """
        UPDATE ir_filters
           SET domain = REPLACE(domain, 'date_planned', 'date_commitment'),
               context = REPLACE(context, 'date_planned', 'date_commitment')
         WHERE model_id IN ('purchase.order', 'purchase.order.line')
           AND (domain LIKE '%%date_planned%%' OR context LIKE '%%date_planned%%')
    """
    )
