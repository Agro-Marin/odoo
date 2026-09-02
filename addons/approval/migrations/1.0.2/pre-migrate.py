import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE approval_request
        DROP COLUMN IF EXISTS quick_approve_token,
        DROP COLUMN IF EXISTS quick_approve_expires_at,
        DROP COLUMN IF EXISTS quick_approve_url,
        DROP COLUMN IF EXISTS qr_code
        """,
    )

    cr.execute(
        """
        ALTER TABLE approval_category
        DROP COLUMN IF EXISTS quick_approve_ttl_hours
        """,
    )

    cr.execute(
        """
        DELETE FROM ir_config_parameter
        WHERE key = 'approval.quick_approve.secret'
        """,
    )
    secret_dropped = cr.rowcount

    cr.execute(
        """
        UPDATE ir_rule r
        SET domain_force = %s,
            name = %s
        FROM ir_model_data d
        WHERE d.res_id = r.id
          AND d.model = 'ir.rule'
          AND d.module = 'approval'
          AND d.name = 'approval_request_user_read'
        """,
        (
            (
                "[\n"
                "                '|', '|',\n"
                "                ('request_owner_id', '=', user.id),\n"
                "                ('approver_ids.user_id', '=', user.id),\n"
                "                ('approver_ids.delegate_id', '=', user.id)\n"
                "            ]"
            ),
            "Approval Request: user read own or approver or delegate",
        ),
    )
    cr.execute(
        """
        UPDATE ir_rule r
        SET domain_force = %s,
            name = %s
        FROM ir_model_data d
        WHERE d.res_id = r.id
          AND d.model = 'ir.rule'
          AND d.module = 'approval'
          AND d.name = 'approval_request_user_write'
        """,
        (
            (
                "[\n"
                "                '|', '|',\n"
                "                ('request_owner_id', '=', user.id),\n"
                "                ('approver_ids.user_id', '=', user.id),\n"
                "                ('approver_ids.delegate_id', '=', user.id)\n"
                "            ]"
            ),
            "Approval Request: user write own or approver or delegate",
        ),
    )
    _logger.info(
        "t22503: refreshed approval.request user read/write ir.rule with delegate path."
    )

    cr.execute(
        """
        UPDATE mail_activity
        SET note = NULL
        WHERE active = true
          AND note LIKE %s
        """,
        ("%/approval/quick/%",),
    )
    activities_cleaned = cr.rowcount

    _logger.info(
        "t22503: dropped quick_approve columns + %d secret(s); "
        "cleaned note on %d open mail.activity records.",
        secret_dropped,
        activities_cleaned,
    )
