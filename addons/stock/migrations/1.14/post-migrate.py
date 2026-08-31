import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1
          FROM stock_picking_type
         WHERE warehouse_id IS NOT NULL
           AND COALESCE(color, 0) <> 0
         LIMIT 1
        """
    )
    if cr.fetchone():
        _logger.info(
            "stock: operation types already carry colours; leaving them alone."
        )
        return

    cr.execute(
        """
        WITH ranked AS (
            SELECT id AS warehouse_id,
                   (row_number() OVER (PARTITION BY company_id ORDER BY id) - 1) % 12
                       AS colour
              FROM stock_warehouse
        )
        UPDATE stock_picking_type pt
           SET color = ranked.colour
          FROM ranked
         WHERE pt.warehouse_id = ranked.warehouse_id
           AND COALESCE(pt.color, 0) <> ranked.colour
        """
    )
    _logger.info("stock: recoloured %s operation types by warehouse.", cr.rowcount)
