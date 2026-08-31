r"""Post-migration: carry over stock_blocked_location's own data migrations.

The blocking feature was absorbed into stock (base 1.25 re-homes its xml ids and
deletes its module row), and the addon's ``migrations/`` went with it. A database
that never reached the addon's 19.0.3.0.0 still carries rows the absorbed code
would have fixed, and nothing else will now fix them:

    block_type set on a non-internal location. ``_check_block_type_usage``
    refuses those, so the row survives until the first write that touches it and
    then raises -- long after the upgrade, on somebody else's save.

**This runs post, through the ORM, and the reason is ``effective_block_type``.**
Clearing ``block_type`` in raw SQL -- which is what the addon's own 19.0.3.0.0
did -- leaves the stored, recursive ``effective_block_type`` at its old value on
that row and on its whole subtree, and nothing marks it for recomputation. The
stale value is not inert: ``hard`` is in ``INCOMING_BLOCK_TYPES``, so a customer
location left reading ``hard`` refuses every delivery into it for anyone without
the hard-block override, with no UI anywhere showing why. Writing through the
ORM recomputes the row and cascades down the subtree.

The addon's 19.0.4.0.0 warning about blocked locations with no reason is kept
too: the location form requires one, so those rows are the ones whose next
manual save will ask for it.
"""

import logging
import typing

from odoo import api

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    _clear_blocks_on_non_internal_locations(env)
    _resync_effective_block_type(env)
    _warn_about_blocks_with_no_reason(env)


def _clear_blocks_on_non_internal_locations(env: api.Environment) -> None:
    offending = (
        env["stock.location"]
        .with_context(active_test=False)
        .search(
            [
                ("block_type", "!=", "none"),
                ("usage", "not in", ["internal"]),
            ],
        )
    )
    for location in offending:
        _logger.warning(
            "stock 1.13: clearing the %s block on %s, which is a %s location -- "
            "only internal locations can be blocked",
            location.block_type,
            location.display_name,
            location.usage,
        )
    if offending:
        offending.write({"block_type": "none"})


def _resync_effective_block_type(env: api.Environment) -> None:
    # Every gate reads effective_block_type, never block_type, so a stored value
    # that disagrees with its own compute is the whole feature being wrong in
    # silence -- under-enforcing (a quarantine that is not one) as readily as
    # over-enforcing. Only a raw-SQL writer can produce the disagreement, and
    # the absorbed addon had one: its 19.0.3.0.0 cleared block_type in SQL. One
    # pass over a small table buys the invariant unconditionally.
    locations = env["stock.location"].with_context(active_test=False).search([])
    locations.modified(["block_type"])
    env.flush_all()


def _warn_about_blocks_with_no_reason(env: api.Environment) -> None:
    unexplained = (
        env["stock.location"]
        .with_context(active_test=False)
        .search([("block_type", "!=", "none"), ("block_reason", "in", [False, ""])])
    )
    if not unexplained:
        return
    _logger.warning(
        "stock 1.13: %d blocked location(s) carry no blocking reason. The "
        "location form requires one, so the next manual save of each will ask",
        len(unexplained),
    )
    for location in unexplained:
        _logger.warning(
            "stock 1.13: %s is %s with no reason recorded",
            location.display_name,
            location.block_type,
        )
