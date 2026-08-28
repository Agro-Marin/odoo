"""Carry the inventory-valuation closing cursor onto ``account.move`` (1.2).

The cursor used to be a comma-separated list of at most ten ``account.move`` ids
in ``ir.config_parameter`` under ``<company_id>.stock_valuation_closing_ids``.
It is now ``account.move.is_stock_valuation_closing``.

Without this the first closing after the upgrade finds no cursor,
``_get_location_valuation_vals`` drops its ``date >`` filter and re-aggregates
every move since the beginning of time -- exactly the double count the new
storage exists to prevent.

The parameter is deleted once its ids are carried over, so a re-run is a no-op
rather than a second pass over rows it already flagged.
"""

import logging

_logger = logging.getLogger(__name__)

SUFFIX = ".stock_valuation_closing_ids"


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT key, value FROM ir_config_parameter WHERE key LIKE %s",
        [f"%{SUFFIX}"],
    )
    rows = cr.fetchall()
    if not rows:
        return

    move_ids = set()
    keys = []
    for key, value in rows:
        keys.append(key)
        for chunk in (value or "").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                move_ids.add(int(chunk))

    if move_ids:
        # `stock_valuation_closing_cutoff` is left NULL: these entries never
        # recorded what they covered, and `_get_last_closing_date` still knows how
        # to approximate it from the state-tracking message for them. The first
        # closing written after the upgrade carries the exact value.
        cr.execute(
            "UPDATE account_move SET is_stock_valuation_closing = TRUE WHERE id = ANY(%s)",
            [sorted(move_ids)],
        )
        _logger.info(
            "stock_account: flagged %s existing inventory valuation closing entries",
            cr.rowcount,
        )
    cr.execute("DELETE FROM ir_config_parameter WHERE key = ANY(%s)", [keys])
