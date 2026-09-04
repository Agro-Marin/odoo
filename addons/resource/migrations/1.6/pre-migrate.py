import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

SCRATCH_TABLE = "_resource_mig_1_6_null_percentage"


def migrate(cr, version):
    if not version:
        return

    cr.execute(SQL("DROP TABLE IF EXISTS %s", SQL.identifier(SCRATCH_TABLE)))
    cr.execute(
        SQL(
            """
            CREATE TABLE %s AS
            SELECT id
              FROM resource_reservation
             WHERE allocated_percentage IS NULL
            """,
            SQL.identifier(SCRATCH_TABLE),
        )
    )
    if not cr.rowcount:
        cr.execute(SQL("DROP TABLE %s", SQL.identifier(SCRATCH_TABLE)))
        return

    _logger.warning(
        "resource 1.6: %s reservation(s) held a NULL allocated_percentage and are"
        " set to 100. A NULL satisfied the old CHECK -- SQL treats an unknown"
        " comparison as met -- while the ORM read it as 0.0, so the overlap sweep"
        " counted those rows at full capacity and allocated_hours counted them at"
        " none. allocated_hours is recomputed in post-migrate.",
        cr.rowcount,
    )
    cr.execute(
        SQL(
            """
            UPDATE resource_reservation
               SET allocated_percentage = 100
             WHERE allocated_percentage IS NULL
            """
        )
    )
