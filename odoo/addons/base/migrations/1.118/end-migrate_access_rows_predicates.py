"""Stored access rows name the predicates their domains spell out.

base.user_has_access, base.is_member and mail.follows say what a condition on
a field whose search reads the user said: 1.117 took such a condition for a
fixed filter beside the reach all. The rows data does not reach (noupdate rows
and the database's own) are read again by the recognizer, which now knows
those fields, and rewritten when the rows it proposes are proven equal.
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
        .search([("reach", "in", [False, "all"]), ("domain", "!=", False)])
    )
    _logger.info(
        "base 1.118: %(converted)s access rows name a predicate or read their reach "
        "through anchors (%(split)s split); %(unanchored)s kept their domain for "
        "want of a declared anchor or an installed predicate, %(unproven)s because "
        "the reach proposed was not proven equal; %(unreached)s rows of the reach "
        "all whose filter reads the user keep it as their domain",
        rows._rows_to_reach(),
    )
