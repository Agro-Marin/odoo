import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

IMAGE_FIELDS = ("image_1920", "image_1024", "image_512", "image_256", "image_128")


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            """
            UPDATE ir_attachment a
               SET res_model = 'res.partner', res_id = e.partner_id
              FROM hr_employee e
             WHERE a.res_model = 'hr.employee'
               AND a.res_id = e.id
               AND a.res_field = ANY(%s)
               AND NOT EXISTS (
                       SELECT 1 FROM ir_attachment p
                        WHERE p.res_model = 'res.partner'
                          AND p.res_id = e.partner_id
                          AND p.res_field = a.res_field)
            """,
            list(IMAGE_FIELDS),
        )
    )
    moved = cr.rowcount
    cr.execute(
        SQL(
            "DELETE FROM ir_attachment"
            " WHERE res_model = 'hr.employee' AND res_field = ANY(%s)",
            list(IMAGE_FIELDS),
        )
    )
    _logger.info(
        "employee images: %s attachments moved onto the work contact, %s dropped"
        " because the contact already had that size",
        moved,
        cr.rowcount,
    )
