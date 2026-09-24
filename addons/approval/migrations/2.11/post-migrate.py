import logging

from odoo.db.schema import table_exists
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # approval.gate is gone since 2.14, so a database older than 2.11 upgrading
    # past both never had the table
    if not version or not table_exists(cr, "approval_gate"):
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
