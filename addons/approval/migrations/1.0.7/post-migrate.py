import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute(
        """
        UPDATE approval_request
        SET name = NULL
        WHERE state = 'new'
          AND date_confirmed IS NULL
          AND name IS NOT NULL
        """,
    )
    if cr.rowcount:
        _logger.info(
            "19.0.1.0.7: cleared the stored placeholder name on %d draft(s).",
            cr.rowcount,
        )

    cr.execute(
        "ALTER TABLE approval_request DROP COLUMN IF EXISTS approver_compute_ms",
    )
    cron = env.ref("approval.ir_cron_performance_report", raise_if_not_found=False)
    if cron:
        cron.unlink()
        _logger.info("19.0.1.0.7: removed the weekly performance-report cron.")

    cr.execute(
        "ALTER TABLE approval_request DROP COLUMN IF EXISTS sla_status",
    )
