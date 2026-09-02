"""Retire the working-schedule and holiday columns, and the old overlap guard.

19.0.1.0.0 drops the ``resource``-backed feature set from ``date.range``. It
never worked: ``_compute_business_days_with_calendar`` called
``resource.calendar.get_work_days_data``, a method that does not exist in Odoo
19 (it is ``get_work_duration_data``), so setting a Working Schedule on any
range raised ``AttributeError`` on create. Nothing in the code base read the
fields it fed, and no test covered them.

Also drops:

* ``date_range_daterange_idx``, the hand-rolled partial GiST index from the old
  ``init()``. The ``date_range_no_overlap`` exclusion constraint builds its own,
  wider index, which supersedes it.
* ``date_range_date_range_uniq``. Uniqueness on ``name`` moved to a Python
  constraint because ``name`` is translated: the column holds one JSON document
  per record, so the SQL index compared whole documents and two ranges called
  "Season A" stopped colliding as soon as one of them was translated.

``active`` becomes a plain stored column instead of a computed one; existing
values carry over untouched, but NULLs (rows written but never flushed by an
older version) are normalised so the new exclusion predicate sees them.

The manifest dependency moves from ``resource`` to ``web``. ``resource`` was
only ever there for the working-schedule fields dropped here; ``web`` is the
real dependency, since the module ships backend assets that patch the domain
editor, and it was previously satisfied only transitively.
"""

import logging

_logger = logging.getLogger(__name__)

_DROPPED_COLUMNS = (
    "resource_calendar_id",
    "working_hours",
    "daily_working_hours",
    "exclude_public_holidays",
    "holiday_count",
)


def migrate(cr, version):
    if not version:
        return

    for column in _DROPPED_COLUMNS:
        cr.execute(f'ALTER TABLE date_range DROP COLUMN IF EXISTS "{column}"')

    cr.execute("DROP INDEX IF EXISTS date_range_daterange_idx")
    cr.execute(
        "ALTER TABLE date_range DROP CONSTRAINT IF EXISTS date_range_date_range_uniq"
    )

    cr.execute("UPDATE date_range SET active = TRUE WHERE active IS NULL")

    # allow_overlap is a new stored related column; seed it so the exclusion
    # constraint added right after this script sees the real values instead of
    # NULL, which its predicate would read as "overlap allowed".
    cr.execute("""
        ALTER TABLE date_range
        ADD COLUMN IF NOT EXISTS allow_overlap boolean
    """)
    cr.execute("""
        UPDATE date_range dr
        SET allow_overlap = COALESCE(t.allow_overlap, FALSE)
        FROM date_range_type t
        WHERE t.id = dr.type_id AND dr.allow_overlap IS DISTINCT FROM t.allow_overlap
    """)

    _report_existing_overlaps(cr)


def _report_existing_overlaps(cr):
    """Name the overlaps the old guard let through, before the schema step trips.

    ``date_range_no_overlap`` cannot be created while the table already breaks
    it. Odoo logs that as one line about a constraint, which tells an
    administrator nothing about which records to fix — and the old check let a
    lot through: it compared companies with ``= NULL`` (never true), so every
    company-less range skipped it entirely. Listing the offenders here turns a
    cryptic schema warning into a work list. Nothing is deleted or changed; the
    records stay exactly as they are and the Python constraint still guards
    every new write.
    """
    cr.execute("""
        SELECT a.id, a.name->>'en_US', a.date_start, a.date_end,
               b.id, b.name->>'en_US', b.date_start, b.date_end
        FROM date_range a
        JOIN date_range b
          ON b.id > a.id
         AND b.type_id = a.type_id
         AND b.company_id IS NOT DISTINCT FROM a.company_id
         AND b.parent_id IS NOT DISTINCT FROM a.parent_id
         AND daterange(b.date_start, b.date_end, '[]')
             && daterange(a.date_start, a.date_end, '[]')
        WHERE COALESCE(a.active, TRUE) AND COALESCE(b.active, TRUE)
          AND NOT COALESCE(a.allow_overlap, FALSE)
          AND a.date_start <= a.date_end AND b.date_start <= b.date_end
        ORDER BY a.id, b.id
    """)
    conflicts = cr.fetchall()
    if not conflicts:
        return
    _logger.warning(
        "%d pre-existing date range overlap(s) block the new "
        "date_range_no_overlap constraint. The upgrade continues without it; "
        "fix these and re-run an update of date_range to install it:\n%s",
        len(conflicts),
        "\n".join(
            f"  id={a_id} {a_name!r} [{a_start} .. {a_end}]"
            f" overlaps id={b_id} {b_name!r} [{b_start} .. {b_end}]"
            for a_id, a_name, a_start, a_end, b_id, b_name, b_start, b_end in conflicts
        ),
    )
