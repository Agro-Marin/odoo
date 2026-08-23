import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    categories = env["approval.category"].search(
        [("sequence_id", "=", False), ("sequence_code", "!=", False)],
    )
    for category in categories:
        category.write({"sequence_code": category.sequence_code})
    if categories:
        _logger.info("t22196: created sequences for %d categories.", len(categories))

    cr.execute(
        "ALTER TABLE approval_category DROP COLUMN IF EXISTS automated_sequence",
    )
