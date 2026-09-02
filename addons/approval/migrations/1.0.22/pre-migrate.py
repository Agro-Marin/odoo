import logging

_logger = logging.getLogger(__name__)


def _dedupe(cr, table, scope_column, keep_order):
    cr.execute(
        f"""
        DELETE FROM {table} a
        USING {table} b
        WHERE a.{scope_column} = b.{scope_column}
          AND a.user_id = b.user_id
          AND ({keep_order})
        RETURNING a.id
        """,
    )
    removed = cr.fetchall()
    if removed:
        _logger.warning(
            "approval 19.0.1.0.22: deleted %d duplicate %s row(s) before "
            "adding the unique constraint: %s",
            len(removed),
            table,
            sorted(row[0] for row in removed),
        )
    return len(removed)


def migrate(cr, version):
    _dedupe(
        cr,
        "approval_category_approver",
        "category_id",
        "a.id > b.id",
    )
    _dedupe(
        cr,
        "approval_approver",
        "request_id",
        """
        (a.state = 'new' AND b.state <> 'new')
        OR (
            (a.state = 'new') = (b.state = 'new')
            AND a.id > b.id
        )
        """,
    )
