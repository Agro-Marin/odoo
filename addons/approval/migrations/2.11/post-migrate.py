import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            """
            UPDATE approval_gate
               SET enforced = TRUE
             WHERE enforced IS NOT TRUE
         RETURNING model_name, operation
            """
        )
    )
    for model_name, operation in cr.fetchall():
        _logger.info(
            "Code gate %s.%s enforces now; it only watched before.",
            model_name,
            operation,
        )
