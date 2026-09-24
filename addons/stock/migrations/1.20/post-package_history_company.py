import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE stock_package_history history
           SET company_id = picking_company.company_id
          FROM (
                SELECT rel.stock_package_history_id AS history_id,
                       MIN(picking.company_id) AS company_id
                  FROM stock_package_history_stock_picking_rel rel
                  JOIN stock_picking picking ON picking.id = rel.stock_picking_id
                 WHERE picking.company_id IS NOT NULL
                 GROUP BY rel.stock_package_history_id
                HAVING COUNT(DISTINCT picking.company_id) = 1
               ) picking_company
         WHERE history.id = picking_company.history_id
           AND history.company_id != picking_company.company_id
        """
    )
    _logger.info(
        "stock 1.20: %d package history rows moved to the company of their transfer",
        cr.rowcount,
    )
