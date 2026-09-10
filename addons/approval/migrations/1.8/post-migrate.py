import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO approval_approver_decided_step_rel (approver_id, step_id)
        SELECT rel.approver_id, rel.step_id
          FROM approval_approver_step_rel rel
          JOIN approval_approver approver ON approver.id = rel.approver_id
         WHERE approver.state IN ('approved', 'refused')
        ON CONFLICT DO NOTHING
        """,
    )
    if cr.rowcount:
        _logger.info(
            "approval 19.0.1.8.0: %d decided step(s) recorded for rows decided "
            "before a decision named its steps.",
            cr.rowcount,
        )
