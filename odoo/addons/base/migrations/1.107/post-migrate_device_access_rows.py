import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

# ir.access rows loaded before 1.103, and kept noupdate, still read what the
# device models held then: rewrite each one still holding exactly that
_REWRITES = (
    ("user_device", "operation", "r", "ru"),
    ("user_device_admin", "operation", "r", "ru"),
    (
        "user_device_logs",
        "domain",
        "[('user_id', '=', user.id)]",
        "[('device_id.user_id', '=', user.id)]",
    ),
)


def migrate(cr, version):
    if not version:
        return
    for xmlid, column, old, new in _REWRITES:
        cr.execute(
            SQL(
                """
                UPDATE ir_access
                SET %s = %s
                FROM ir_model_data data
                WHERE data.module = 'base'
                  AND data.name = %s
                  AND data.model = 'ir.access'
                  AND ir_access.id = data.res_id
                  AND ir_access.%s = %s
                RETURNING ir_access.id
                """,
                SQL.identifier(column),
                new,
                xmlid,
                SQL.identifier(column),
                old,
            )
        )
        if cr.rowcount:
            _logger.info("base 1.107: base.%s %s %r -> %r", xmlid, column, old, new)
            continue
        cr.execute(
            SQL(
                """
                SELECT ir_access.%s
                FROM ir_access
                JOIN ir_model_data data ON data.res_id = ir_access.id
                WHERE data.module = 'base' AND data.name = %s
                  AND data.model = 'ir.access'
                """,
                SQL.identifier(column),
                xmlid,
            )
        )
        current = cr.fetchone()
        if current and current[0] != new:
            _logger.warning(
                "base 1.107: base.%s has %s %r, neither the old %r nor the new %r;"
                " left as customized, check it by hand",
                xmlid,
                column,
                current[0],
                old,
                new,
            )
    # the for_* flags are stored computes of operation that a SQL rewrite leaves
    # stale, and the form's inverse writes operation back from them
    cr.execute(
        SQL(
            """
            UPDATE ir_access
            SET for_create = position('c' IN operation) > 0,
                for_read = position('r' IN operation) > 0,
                for_write = position('u' IN operation) > 0,
                for_unlink = position('d' IN operation) > 0
            FROM ir_model_data data
            WHERE data.module = 'base'
              AND data.name = ANY(%s)
              AND data.model = 'ir.access'
              AND ir_access.id = data.res_id
              AND operation IS NOT NULL
            """,
            [xmlid for xmlid, column, _old, _new in _REWRITES if column == "operation"],
        )
    )
