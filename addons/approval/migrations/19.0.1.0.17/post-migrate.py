import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE approval_approver a
        SET pending_since = ar.date_confirmed
        FROM approval_request ar
        WHERE ar.id = a.request_id
          AND a.pending_since IS NULL
          AND ar.date_confirmed IS NOT NULL
          AND a.state IN ('pending', 'approved', 'refused')
        """,
    )
    _logger.info(
        "approval 19.0.1.0.17: backfilled pending_since on %d approver row(s).",
        cr.rowcount,
    )

    cr.execute(
        "DELETE FROM ir_config_parameter WHERE key = 'approval.sequence.category'",
    )
    removed = cr.rowcount
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'approval'
          AND name = 'config_param_sequence_category'
        """,
    )
    if removed:
        _logger.info(
            "approval 19.0.1.0.17: removed the unread "
            "approval.sequence.category parameter.",
        )
