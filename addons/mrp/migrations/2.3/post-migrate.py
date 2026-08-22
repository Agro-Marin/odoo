import logging

_logger = logging.getLogger(__name__)


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
    if not _column_exists(cr, "mrp_workorder", "reservation_id"):
        return

    cr.execute("""
        UPDATE resource_reservation rr
           SET res_model = 'mrp.workorder',
               res_id = wo.id
          FROM mrp_workorder wo
         WHERE wo.reservation_id = rr.id
           AND (rr.res_model IS NULL OR rr.res_id IS NULL)
    """)
    repaired = cr.rowcount
    if repaired:
        _logger.warning(
            "mrp 2.3: %d work order reservation(s) had no origin reference and "
            "were repaired before dropping the column.",
            repaired,
        )

    cr.execute("""
        SELECT count(*)
          FROM mrp_workorder wo
          JOIN resource_reservation rr ON wo.reservation_id = rr.id
         WHERE rr.res_model = 'mrp.workorder'
           AND rr.res_id IS DISTINCT FROM wo.id
    """)
    mismatched = cr.fetchone()[0]
    if mismatched:
        _logger.warning(
            "mrp 2.3: %d reservation(s) are named by a work order's "
            "reservation_id but carry a different res_id; the ledger link "
            "wins and the column is being dropped.",
            mismatched,
        )

    cr.execute('ALTER TABLE "mrp_workorder" DROP COLUMN "reservation_id"')
    _logger.info("mrp 2.3: dropped mrp_workorder.reservation_id.")
