import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE approval_approver a
        SET decision_date = ar.date_approval_granted
        FROM approval_request ar
        WHERE ar.id = a.request_id
          AND a.state = 'approved'
          AND a.decision_date IS NULL
          AND ar.date_approval_granted IS NOT NULL
        """,
    )
    approved_filled = cr.rowcount

    cr.execute(
        """
        UPDATE approval_approver a
        SET decision_date = ar.date_refused
        FROM approval_request ar
        WHERE ar.id = a.request_id
          AND a.state = 'refused'
          AND a.decision_date IS NULL
          AND ar.date_refused IS NOT NULL
          AND (a.refusal_reason_id IS NOT NULL OR a.note IS NOT NULL)
        """,
    )
    refused_filled = cr.rowcount

    if approved_filled or refused_filled:
        _logger.info(
            "19.0.1.0.8: backfilled decision_date on %d approved and "
            "%d genuine-refusal approver row(s).",
            approved_filled,
            refused_filled,
        )
