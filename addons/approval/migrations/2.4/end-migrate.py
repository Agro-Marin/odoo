import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Convert every approval category to steps that route its requests the same.

    An end-stage script on purpose: it runs once every module of the load is in the
    registry, so the blockers and path sources modules add (approval_hr's manager)
    take part. A category with a blocker keeps its approver list and is logged with
    the reasons. Requests already confirmed on the list keep routing by it.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    result = env["approval.category"]._convert_every_category_to_steps()
    for category in result["converted"]:
        _logger.info(
            "approval category %s (#%s) now routes by %s step(s)",
            category.name,
            category.id,
            len(category.step_ids),
        )
    for category, blockers in result["blocked"].items():
        _logger.warning(
            "approval category %s (#%s) keeps its approver list: %s",
            category.name,
            category.id,
            " ".join(blockers),
        )
