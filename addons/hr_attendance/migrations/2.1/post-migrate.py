import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Back-fill `hr.attendance.overtime.line.attendance_id`.

    The line used to be joined to its attendance by an implicit
    `(employee_id, time_start == check_in)` match; the column that makes that
    relation real is new, so existing rows carry NULL until this fills them.
    The old match key is exactly `(employee_id, time_start)` against the
    attendance's `(employee_id, check_in)`, and an employee cannot have two
    attendances with the same check-in (the overlap constraint forbids it), so
    the join is one-to-one and unambiguous.
    """
    if not column_exists(cr, "hr_attendance_overtime_line", "attendance_id"):
        _logger.warning("attendance_id column absent; ORM did not create it")
        return
    cr.execute(
        """
        UPDATE hr_attendance_overtime_line line
           SET attendance_id = att.id
          FROM hr_attendance att
         WHERE line.attendance_id IS NULL
           AND att.employee_id = line.employee_id
           AND att.check_in = line.time_start
        """
    )
    filled = cr.rowcount
    cr.execute(
        "SELECT count(*) FROM hr_attendance_overtime_line WHERE attendance_id IS NULL"
    )
    (orphans,) = cr.fetchone()
    _logger.info(
        "hr_attendance: linked %s overtime line(s) to their attendance; "
        "%s line(s) matched none and are left detached",
        filled,
        orphans,
    )
    if orphans:
        # A line whose attendance no longer exists derived from a shift that was
        # deleted without regenerating; it can no longer be recomputed and only
        # inflates totals. Nothing points at it any more, so remove it.
        cr.execute(
            "DELETE FROM hr_attendance_overtime_line WHERE attendance_id IS NULL"
        )
        _logger.info("hr_attendance: removed %s detached overtime line(s)", orphans)
