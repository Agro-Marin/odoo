import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE approval_request r
           SET company_id = COALESCE(
                   (SELECT u.company_id FROM res_users u WHERE u.id = r.request_owner_id),
                   (SELECT id FROM res_company ORDER BY id LIMIT 1)
               )
         WHERE r.company_id IS NULL
        """,
    )
    if cr.rowcount:
        _logger.info(
            "approval 19.0.1.0.26: backfilled company_id on %d request(s) that "
            "the multi-company rule hid from their own owner.",
            cr.rowcount,
        )

    cr.execute("ALTER TABLE approval_category DROP COLUMN IF EXISTS has_payment_method")

    cr.execute(
        "DELETE FROM ir_config_parameter WHERE key = 'approval.sequence.manual'",
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'approval'
           AND name IN ('config_param_sequence_manual', 'view_res_users_form')
        """,
    )
