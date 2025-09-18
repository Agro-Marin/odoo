"""Pre-migration script for purchase module version 1.3.

This migration prepares existing data for the change where:
- `selected_seller_id` becomes a stored computed field
- `price_unit_shadow` becomes a stored computed field

Without this migration, existing manually-set prices could be overwritten
when the computed fields recompute after the module update.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Prepare existing purchase order lines for stored computed fields.

    Sets price_unit_shadow = price_unit for all lines where shadow is not set.
    This ensures existing prices are treated as "intentional" and won't be
    overwritten by the new compute logic.
    """
    if not version:
        return

    _logger.info("Preparing purchase order lines for selected_seller_id storage...")

    # Set price_unit_shadow = price_unit for all lines where shadow is NULL
    # This "locks in" existing prices as intentional, preventing recomputation
    cr.execute("""
        UPDATE purchase_order_line
        SET price_unit_shadow = price_unit
        WHERE price_unit_shadow IS NULL
          AND price_unit IS NOT NULL
          AND display_type IS NULL
    """)

    updated_count = cr.rowcount
    _logger.info(
        "Set price_unit_shadow for %d purchase order lines to preserve existing prices",
        updated_count,
    )
