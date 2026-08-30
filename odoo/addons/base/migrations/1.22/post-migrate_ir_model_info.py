import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("UPDATE ir_model SET info = NULL WHERE info = %s", (object.__doc__,))
    _logger.info(
        "base 1.22: cleared the leaked object.__doc__ from ir_model.info on %s "
        "model(s); reflection recomputes each on its module's next upgrade",
        cr.rowcount,
    )
