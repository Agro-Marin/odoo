import logging

from odoo.db.schema import drop_index

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    drop_index(cr, "res_device_log__last_activity_index", "res_device_log")
    _logger.info("base 1.103: dropped res_device_log__last_activity_index")
