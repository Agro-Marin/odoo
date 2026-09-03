import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # the pairs pre-migrate parked, now that mrp.unbuild.lot_ids exists and its
    # relation table with it. See 2.5/pre-migrate.py for why it takes two steps.
    cr.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_name = 'mrp_unbuild_lot_id_backfill'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        INSERT INTO mrp_unbuild_stock_lot_rel (mrp_unbuild_id, stock_lot_id)
             SELECT backfill.unbuild_id, backfill.lot_id
               FROM mrp_unbuild_lot_id_backfill backfill
               JOIN mrp_unbuild unbuild ON unbuild.id = backfill.unbuild_id
               JOIN stock_lot lot ON lot.id = backfill.lot_id
        ON CONFLICT DO NOTHING
        """
    )
    _logger.info("mrp.unbuild: moved %s lot_id value(s) to lot_ids", cr.rowcount)
    cr.execute("DROP TABLE mrp_unbuild_lot_id_backfill")
