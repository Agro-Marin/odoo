"""The ir.access Read / Update / Create / Delete flags are read from `operation`.

They were stored beside it, so a migration that rewrote `operation` by SQL left
them behind (1.106's device rows until 2d49cad71972), and editing any flag of
such a row wrote the stale four back into `operation`. They are no longer
stored; their columns go. Losing this step is harmless: nothing reads the
columns once the fields are not stored, which is why it runs last, after every
older migration that still writes them.
"""

import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

COLUMNS = ("for_read", "for_write", "for_create", "for_unlink")


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            "ALTER TABLE ir_access %s",
            SQL(", ").join(
                SQL("DROP COLUMN IF EXISTS %s", SQL.identifier(column))
                for column in COLUMNS
            ),
        )
    )
    _logger.info("base 1.111: ir.access %s are read from its operation", COLUMNS)
