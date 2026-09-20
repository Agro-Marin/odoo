import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # After base's own views have been reloaded, so what is left naming the old
    # fields is a saved filter or a customisation this upgrade did not write.
    cr.execute("""
        SELECT 'ir.filters', id, name FROM ir_filters
         WHERE model_id = 'ir.cron'
           AND (domain LIKE '%interval_number%' OR domain LIKE '%interval_type%'
                OR context LIKE '%interval_number%' OR context LIKE '%interval_type%')
        UNION ALL
        SELECT 'ir.ui.view', id, name FROM ir_ui_view
         WHERE model = 'ir.cron'
           AND (arch_db::text LIKE '%interval_number%' OR arch_db::text LIKE '%interval_type%')
    """)
    for model, record_id, name in cr.fetchall():
        _logger.warning(
            "base 1.50: %s %d (%s) still names interval_number or interval_type on"
            " ir.cron, now repeat_interval and repeat_unit.",
            model,
            record_id,
            name,
        )
