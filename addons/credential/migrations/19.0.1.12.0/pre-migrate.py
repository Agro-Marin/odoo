"""Drop 'cache_hits' and 'cache_misses' from 'credential.credential'.

Two counters nothing ever incremented. They appeared in exactly two places: their own
field definitions, and '_PROTECTED_STATS_FIELDS' -- the write guard, which was therefore
protecting a pair of values permanently equal to zero.

They are not reinstated with a writer. The session cache they were meant to describe
('credential/tools/session_cache.py') exists to avoid touching the database on a
credential read; incrementing a stored counter on every hit would put a write back on
exactly the path the cache removes.

Same defensive shape as 'api_transport/migrations/19.0.1.19.0': a non-zero row means the
premise is wrong, so the drop is skipped and logged rather than forced.
"""

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
