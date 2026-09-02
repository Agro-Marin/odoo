import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        WITH ranked AS (
            SELECT a.request_id,
                   a.refusal_reason_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.request_id
                       ORDER BY a.write_date DESC NULLS LAST, a.id DESC
                   ) AS rn
              FROM approval_approver a
             WHERE a.refusal_reason_id IS NOT NULL
        )
        UPDATE approval_request r
           SET refusal_reason_id = ranked.refusal_reason_id
          FROM ranked
         WHERE ranked.request_id = r.id
           AND ranked.rn = 1
           AND r.refusal_reason_id IS NULL
           AND r.state = 'refused'
        """,
    )
    backfilled = cr.rowcount
    _logger.info(
        "t21613 post-migrate: backfilled %s refusal_reason_id values", backfilled
    )

    cr.execute(
        """
        WITH inferred AS (
            SELECT r.id AS request_id,
                   COALESCE(
                       r.date_refused,
                       (
                           SELECT MAX(a.write_date)
                             FROM approval_approver a
                            WHERE a.request_id = r.id
                              AND a.state = 'refused'
                       ),
                       r.write_date,
                       NOW() AT TIME ZONE 'UTC'
                   ) AS inferred_date
              FROM approval_request r
             WHERE r.state = 'refused'
               AND r.refusal_reason_id IS NULL
        )
        UPDATE approval_request r
           SET refusal_reason_id = d.res_id,
               refusal_note = 'no reason captured',
               date_refused = i.inferred_date
          FROM inferred i,
               ir_model_data d
         WHERE i.request_id = r.id
           AND d.module = 'approval'
           AND d.name = 'refusal_reason_data_migration'
           AND d.model = 'approval.refusal.reason'
        """,
    )
    marked = cr.rowcount
    _logger.info(
        "t21613 post-migrate: marked %s legacy refused with 'Data migration' reason",
        marked,
    )

    cr.execute(
        """
        UPDATE approval_approver a
           SET refusal_reason_id = d.res_id,
               note = 'no reason captured'
          FROM ir_model_data d,
               approval_request r
         WHERE a.request_id = r.id
           AND a.state = 'refused'
           AND a.refusal_reason_id IS NULL
           AND r.refusal_reason_id = d.res_id
           AND d.module = 'approval'
           AND d.name = 'refusal_reason_data_migration'
           AND d.model = 'approval.refusal.reason'
        """,
    )
    approvers_marked = cr.rowcount
    _logger.info(
        "t21613 post-migrate: mirrored 'Data migration' reason on %s approver(s)",
        approvers_marked,
    )

    cr.execute(
        """
        SELECT COUNT(*)
          FROM approval_request
         WHERE state IN ('cancel', 'revision')
        """,
    )
    leftover_requests = cr.fetchone()[0]
    cr.execute(
        """
        SELECT COUNT(*)
          FROM approval_approver
         WHERE state IN ('cancel', 'revision')
        """,
    )
    leftover_approvers = cr.fetchone()[0]
    if leftover_requests or leftover_approvers:
        raise RuntimeError(
            "t21613 post-migrate sanity check failed: "
            f"{leftover_requests} requests and {leftover_approvers} approvers "
            "still in cancel/revision state.",
        )
