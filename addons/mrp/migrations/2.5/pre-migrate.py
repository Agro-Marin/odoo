import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # mrp.unbuild.lot_id (m2o) becomes lot_ids (m2m), so that one unbuild order
    # can take every serial its production made. The old column is read here and
    # not in post-migrate: the relation table does not exist yet, and by the time
    # it does the column may already be gone -- `ir.model.fields.unlink` drops the
    # column of a field the model no longer declares. So the pairs are parked in a
    # table of our own and post-migrate inserts them.
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'mrp_unbuild'
           AND column_name = 'lot_id'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        CREATE TABLE IF NOT EXISTS mrp_unbuild_lot_id_backfill (
            unbuild_id integer PRIMARY KEY,
            lot_id integer NOT NULL
        )
        """
    )
    cr.execute(
        """
        INSERT INTO mrp_unbuild_lot_id_backfill (unbuild_id, lot_id)
             SELECT id, lot_id
               FROM mrp_unbuild
              WHERE lot_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    _logger.info("mrp.unbuild: parked %s lot_id value(s) for lot_ids", cr.rowcount)
