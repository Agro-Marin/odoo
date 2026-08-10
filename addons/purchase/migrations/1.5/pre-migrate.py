"""Pre-migration: rename date_planned -> date_commitment on purchase models.

The field held the date a human committed to — the arrival date promised by
the vendor — which is the concept sale already stores as
``sale.order.date_commitment``. Under the old name it clashed with a different
concept: sale's ``date_planned`` is a derived, *unstored* estimate. Sharing one
name for one concept lets base_order reason about it (``order.mixin``'s
``is_late`` domain now does) instead of each module meaning its own thing.

Renaming in ``pre`` is what makes this safe. Left to itself the ORM would find
no ``date_commitment`` column, create an empty one, and treat ``date_planned``
as an unknown leftover — every promised date on both tables silently lost.

``date_planned`` is deliberately untouched wherever it means something else:
stock's scheduling dates on stock.move / stock.picking, the procurement
``values`` dicts that feed the rules, and the replenishment wizard.
"""


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
            # A partial earlier run left an ORM-created empty column: keep the
            # data that is in the old one.
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

        # Delete stale field record -- ORM will recreate with correct definition
        cr.execute(
            """
            DELETE FROM ir_model_fields
             WHERE model = %s AND name = 'date_planned'
        """,
            [model],
        )

    # Drop old indexes -- ORM recreates them on update
    cr.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename IN ('purchase_order', 'purchase_order_line')
          AND indexname LIKE '%%date_planned%%'
    """)
    for (idx_name,) in cr.fetchall():
        cr.execute(f'DROP INDEX IF EXISTS "{idx_name}"')

    # The mail templates ship inside <odoo noupdate="1">, so the renamed XML
    # never reaches a database that already has them: the stored body would go
    # on calling object.date_planned and every RFQ and vendor-reminder mail
    # would fail to render. Scoped to purchase's own templates -- a
    # stock.picking template may legitimately say object.date_planned, and that
    # field still exists.
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

    # Saved user filters keep the field name in their stored domain/context and
    # are not reloaded from XML, so they would break on the removed name.
    cr.execute(
        """
        UPDATE ir_filters
           SET domain = REPLACE(domain, 'date_planned', 'date_commitment'),
               context = REPLACE(context, 'date_planned', 'date_commitment')
         WHERE model_id IN ('purchase.order', 'purchase.order.line')
           AND (domain LIKE '%%date_planned%%' OR context LIKE '%%date_planned%%')
    """
    )
