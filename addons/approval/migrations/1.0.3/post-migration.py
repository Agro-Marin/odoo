import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    category = env.ref(
        "approval.approval_category_data_procurement",
        raise_if_not_found=False,
    )
    if not category:
        return
    if category.sequence_code == "PROC":
        category.sequence_code = "PROCURE"
        _logger.info(
            "t22279: renamed approval.category #%s sequence_code PROC -> PROCURE",
            category.id,
        )
    if (
        category.sequence_id
        and category.sequence_id.prefix
        and category.sequence_id.prefix.startswith("PROC/")
    ):
        new_prefix = "PROCURE/" + category.sequence_id.prefix[len("PROC/") :]
        category.sequence_id.prefix = new_prefix
        _logger.info(
            "t22279: updated ir.sequence #%s prefix to %s",
            category.sequence_id.id,
            new_prefix,
        )
