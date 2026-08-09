"""Post-migration: drop `mrp_workorder.leave_id`.

Work order bookings moved from `resource.calendar.leaves` to
`resource.reservation`; `leave_id` was left behind carrying a "Deprecated: use
reservation_id instead" note and, at the time of removal, no readers anywhere
in odoo, enterprise or agromarin. Removing the field from the model does not
drop the column, so this does.

The leave rows themselves are not touched: they belong to
`resource.calendar.leaves` and may be referenced elsewhere. Only the pointer
from the work order goes.
"""


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _column_exists(cr, "mrp_workorder", "leave_id"):
        return
    cr.execute('ALTER TABLE "mrp_workorder" DROP COLUMN "leave_id"')
