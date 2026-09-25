"""Stored access rows read their reach through the models' anchors.

A module's own rows are rewritten when its data loads; this converts the rows
data does not reach: noupdate rows and the database's own. Each is read by the
same recognizer the source rewrite used and changed only when the rows it
proposes are proven equal to its domain and every anchor they read is one the
model declares. Losing this step is harmless, which is why it runs last: an
unconverted row keeps a correct domain.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    rows = (
        env["ir.access"]
        .with_context(active_test=False)
        .search([("reach", "=", False), ("domain", "!=", False)])
    )
    _logger.info(
        "base 1.117: %(converted)s access rows read their reach through anchors "
        "(%(split)s split); %(unanchored)s kept their domain for want of a declared "
        "anchor, %(unproven)s because the reach proposed was not proven equal",
        rows._rows_to_reach(),
    )
