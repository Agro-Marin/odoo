"""Clamp ``allocated_percentage`` into 0..100 before the CHECK lands.

``resource.reservation.allocated_percentage`` gained
``CHECK(allocated_percentage >= 0 AND allocated_percentage <= 100)`` in 1.4.
A value outside that range is not merely untidy: the cumulative overlap sweep
in ``_compute_schedule_overlap_count`` *adds these numbers up*, so a negative
row cancels a real booking, zeroes ``schedule_overlap_count`` and lets a
reservation slip past ``enforcement_mode = 'hard'`` unnoticed.

This runs **pre**-migrate so the repair happens before Odoo tries to add the
constraint: an ALTER TABLE that fails on existing rows is only logged as a
warning, which would leave the table permanently unconstrained.

Rows are clamped rather than deleted — a reservation is a mirror of a consumer
record, and dropping it would silently un-book work that still exists.  The
clamped ids are parked in a scratch table for ``post-migrate`` to recompute
``allocated_hours`` from (a raw UPDATE cannot), and the affected consumers are
logged so the discrepancy can be reconciled by hand.
"""

import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

SCRATCH_TABLE = "_resource_mig_1_4_clamped"


def _backfill_week_type(cr):
    """Give every two-weeks working time a week, as 1.4 now requires.

    ``resource.calendar.attendance.week_type`` was never enforced, and an unset
    one is not inert: ``_attendance_intervals_batch`` buckets on
    ``int(week_type)`` and ``int(False)`` is ``0``, so the line already behaved
    as a first-week line — while ``_works_on_date`` reported that same day as
    not worked.  Materialising the ``'0'`` it was already being treated as
    therefore changes no schedule; it only makes the two agree, and stops the
    new constraint from firing on the next unrelated edit of an old calendar.
    """
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

    # Hand the affected ids to post-migrate: the clamp changes the stored,
    # computed ``allocated_hours``, and the aggregate the consumer carries.
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
