import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # ir.model.info took the first non-empty __doc__ up the registry class's
    # mro(). BaseModel (aliased as AbstractModel), Model and TransientModel all
    # carry __doc__ = None, so the walk ran off the end of the model hierarchy and
    # stored object.__doc__ -- "The base class of the class hierarchy." -- as
    # the Information of nearly every model. Reflection rewrites the rows of
    # the module being upgraded and no others, so upgrading base alone would
    # leave every other module's models holding the leaked value until each of
    # them happened to move.
    cr.execute("UPDATE ir_model SET info = NULL WHERE info = %s", (object.__doc__,))
    _logger.info(
        "base 1.22: cleared the leaked object.__doc__ from ir_model.info on %s "
        "model(s); reflection recomputes each on its module's next upgrade",
        cr.rowcount,
    )
