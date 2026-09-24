import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            """
            UPDATE approval_category
               SET allow_self_approval = FALSE
             WHERE allow_self_approval
         RETURNING id, name->>'en_US', active
            """
        )
    )
    flipped = cr.fetchall()
    for category_id, name, active in sorted(flipped):
        _logger.info(
            "Approval category %s (%s%s) no longer allows self-approval.",
            name,
            category_id,
            "" if active else ", archived",
        )
    _logger.info(
        "approval 19.0.2.13.0: self-approval turned off on %s categories.",
        len(flipped),
    )
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["approval.request"]._grant_upgrade_self_approval_exceptions()
