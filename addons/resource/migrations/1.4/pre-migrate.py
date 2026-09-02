import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

SCRATCH_TABLE = "_resource_mig_1_4_clamped"


def _backfill_week_type(cr):
    cr.execute(
        SQL(
            """
            UPDATE resource_calendar_attendance att
               SET week_type = '0'
              FROM resource_calendar cal
             WHERE att.calendar_id = cal.id
               AND cal.two_weeks_calendar
               AND att.display_type IS NULL
               AND att.week_type IS NULL
            """
        )
    )
    if cr.rowcount:
        _logger.warning(
            "resource 1.4: %s two-weeks working time(s) had no week_type and"
            " were assigned to the first week (the week they already behaved as)",
            cr.rowcount,
        )


def migrate(cr, version):
    if not version:
        return

    _backfill_week_type(cr)

    cr.execute(
        SQL(
            """
            SELECT res_model, COUNT(*), MIN(allocated_percentage),
                   MAX(allocated_percentage)
              FROM resource_reservation
             WHERE allocated_percentage IS NOT NULL
               AND (allocated_percentage < 0 OR allocated_percentage > 100)
          GROUP BY res_model
            """
        )
    )
    offenders = cr.fetchall()
    if not offenders:
        return

    for res_model, count, low, high in offenders:
        _logger.warning(
            "resource 1.4: clamping %s reservation(s) from %s with an"
            " out-of-range allocated_percentage (min=%s, max=%s) into 0..100;"
            " allocated_hours is recomputed in post-migrate",
            count,
            res_model or "an unknown model",
            low,
            high,
        )

    cr.execute(SQL("DROP TABLE IF EXISTS %s", SQL.identifier(SCRATCH_TABLE)))
    cr.execute(
        SQL(
            """
            CREATE TABLE %s AS
            SELECT id
              FROM resource_reservation
             WHERE allocated_percentage IS NOT NULL
               AND (allocated_percentage < 0 OR allocated_percentage > 100)
            """,
            SQL.identifier(SCRATCH_TABLE),
        )
    )
    cr.execute(
        SQL(
            """
            UPDATE resource_reservation
               SET allocated_percentage = LEAST(100, GREATEST(0, allocated_percentage))
             WHERE allocated_percentage IS NOT NULL
               AND (allocated_percentage < 0 OR allocated_percentage > 100)
            """
        )
    )
