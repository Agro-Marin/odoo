import logging

_logger = logging.getLogger(__name__)

NEW_DOMAIN = (
    "[\n"
    "    '|', '|', '|', '|',\n"
    "    ('request_id.request_owner_id', '=', user.id),\n"
    "    ('user_id', '=', user.id),\n"
    "    ('delegate_id', '=', user.id),\n"
    "    ('request_id.approver_ids.user_id', '=', user.id),\n"
    "    ('request_id.approver_ids.delegate_id', '=', user.id)\n"
    "]"
)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_rule
        SET domain_force = %s
        WHERE id = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'approval' AND name = 'approval_approver_user_read'
              AND model = 'ir.rule'
        )
        """,
        (NEW_DOMAIN,),
    )
    if cr.rowcount:
        _logger.info(
            "19.0.1.0.14: widened approval_approver_user_read domain for "
            "co-approver delegates.",
        )
