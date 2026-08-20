import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT pg_size_pretty(pg_relation_size(indexrelid))
          FROM pg_stat_user_indexes
         WHERE indexrelname = 'mail_followers__res_model_index'
        """
    )
    if not (row := cr.fetchone()):
        return
    cr.execute("DROP INDEX IF EXISTS mail_followers__res_model_index")
    _logger.info(
        "Dropped mail_followers__res_model_index (%s); "
        "the unique constraint on (res_model, res_id, partner_id) covers it",
        row[0],
    )
