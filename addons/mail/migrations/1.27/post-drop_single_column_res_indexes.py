import logging

_logger = logging.getLogger(__name__)

REPLACED = ("mail_activity__res_model_index", "mail_activity__res_id_index")


def migrate(cr, version):
    cr.execute(
        """
        SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
          FROM pg_stat_user_indexes
         WHERE indexrelname = ANY(%s)
        """,
        [list(REPLACED)],
    )
    found = cr.fetchall()
    if not found:
        return
    for indexname, __ in found:
        cr.execute(f'DROP INDEX IF EXISTS "{indexname}"')
    _logger.info(
        "Dropped %s; mail_activity_res_model_res_id_index covers both, and the "
        "registry keeps rather than drops an index whose field lost index=True",
        ", ".join(f"{name} ({size})" for name, size in found),
    )
