import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE resource_resource r
           SET partner_id = e.partner_id
          FROM hr_employee e
         WHERE e.resource_id = r.id AND r.partner_id IS DISTINCT FROM e.partner_id
        """
    )
    _logger.info("%s employee resources bound to their party", cr.rowcount)
