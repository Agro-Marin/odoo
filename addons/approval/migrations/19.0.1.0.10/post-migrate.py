import logging

_logger = logging.getLogger(__name__)

NEW_DOMAIN = (
    "[\n"
    "    '|', '|', '|',\n"
    "    ('request_id.request_owner_id', '=', user.id),\n"
    "    ('user_id', '=', user.id),\n"
    "    ('delegate_id', '=', user.id),\n"
    "    ('request_id.approver_ids.user_id', '=', user.id)\n"
    "]"
)
NEW_NAME = "Approval Approver: user read own request, self, delegated, or co-approver"


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_rule
        SET domain_force = %s, name = %s
        WHERE id = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'approval' AND name = 'approval_approver_user_read'
              AND model = 'ir.rule'
        )
        """,
        (NEW_DOMAIN, NEW_NAME),
    )
    if cr.rowcount:
        _logger.info("19.0.1.0.10: widened approval_approver_user_read domain.")

    cr.execute(
        """
        UPDATE approval_category_approver aca
        SET company_id = ac.company_id
        FROM approval_category ac
        WHERE ac.id = aca.category_id
          AND aca.company_id IS DISTINCT FROM ac.company_id
        """,
    )
    if cr.rowcount:
        _logger.info(
            "19.0.1.0.10: backfilled company_id on %d category-approver row(s).",
            cr.rowcount,
        )
