import logging

from odoo.db.schema import column_exists, table_exists
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_TABLE = "credential_credential"
_MODEL = "credential.credential"
_COLUMNS = ("cache_hits", "cache_misses")


def _rows_carrying_a_value(cr, column):
    cr.execute(
        SQL(
            "SELECT count(*) FROM %s WHERE %s IS NOT NULL AND %s <> 0",
            SQL.identifier(_TABLE),
            SQL.identifier(column),
            SQL.identifier(column),
        )
    )
    return cr.fetchone()[0]


def migrate(cr, version):
    if not version:
        return
    if not table_exists(cr, _TABLE):
        return

    for column in _COLUMNS:
        if not column_exists(cr, _TABLE, column):
            continue

        populated = _rows_carrying_a_value(cr, column)
        if populated:
            _logger.warning(
                "%s.%s holds %s non-zero row(s) and was NOT dropped. Nothing in this "
                "fork increments it, so investigate what does before removing it.",
                _TABLE,
                column,
                populated,
            )
            continue

        cr.execute(
            """
            DELETE FROM ir_model_fields f
                  USING ir_model m
                  WHERE f.model_id = m.id
                    AND f.name = %s
                    AND m.model = %s
            """,
            (column, _MODEL),
        )
        removed = cr.rowcount
        cr.execute(
            SQL(
                "ALTER TABLE %s DROP COLUMN IF EXISTS %s",
                SQL.identifier(_TABLE),
                SQL.identifier(column),
            )
        )
        _logger.info(
            "%s: dropped always-zero column %s (%s field definition(s) removed)",
            _TABLE,
            column,
            removed,
        )
