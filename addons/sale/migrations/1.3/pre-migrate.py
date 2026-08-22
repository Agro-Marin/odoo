import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    _logger.info("Migrating sale order line price fields...")

    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'sale_order_line'
          AND column_name = 'price_unit_shadow'
    """)

    if cr.fetchone():
        _logger.info("Renaming price_unit_shadow to price_unit_auto...")
        cr.execute("""
            ALTER TABLE sale_order_line
            RENAME COLUMN price_unit_shadow TO price_unit_auto
        """)
        _logger.info("Column renamed successfully")
    else:
        _logger.info("price_unit_shadow column not found, skipping rename")

    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'sale_order_line'
          AND column_name = 'price_is_manual'
    """)

    if cr.fetchone():
        _logger.info("Dropping price_is_manual column...")
        cr.execute("""
            ALTER TABLE sale_order_line
            DROP COLUMN price_is_manual
        """)
        _logger.info("Column dropped successfully")
    else:
        _logger.info("price_is_manual column not found, skipping drop")

    _logger.info("Setting price_unit_auto for NULL values...")
    cr.execute("""
        UPDATE sale_order_line
        SET price_unit_auto = price_unit
        WHERE price_unit_auto IS NULL
          AND price_unit IS NOT NULL
          AND display_type IS NULL
    """)

    updated_count = cr.rowcount
    _logger.info(
        "Set price_unit_auto for %d sale order lines to preserve existing prices",
        updated_count,
    )

    _logger.info("Sale order line price field migration complete")
