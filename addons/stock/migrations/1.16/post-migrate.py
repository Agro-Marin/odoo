import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("CREATE SEQUENCE IF NOT EXISTS stock_move_completion_seq")
    cr.execute(
        """
        UPDATE stock_move
           SET completion_sequence = id
         WHERE state = 'done'
           AND completion_sequence IS NULL
        """
    )
    backfilled = cr.rowcount
    cr.execute(
        """
        SELECT setval(
            'stock_move_completion_seq',
            GREATEST(COALESCE(MAX(id), 1), 1),
            COALESCE(MAX(id), 0) > 0
        )
          FROM stock_move
        """
    )
    _logger.info(
        "stock: %s done moves take their id as completion order; the sequence"
        " continues from the highest move id.",
        backfilled,
    )
