import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE approval_approver
        SET decided_by_user_id = user_id
        WHERE decision_date IS NOT NULL
          AND decided_by_user_id IS NULL
        """,
    )
    _logger.info(
        "approval 19.0.1.0.21: backfilled decided_by_user_id on %d "
        "decided approver row(s).",
        cr.rowcount,
    )
