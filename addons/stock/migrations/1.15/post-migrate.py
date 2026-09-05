import logging

from psycopg.types.json import Json

_logger = logging.getLogger(__name__)

UNGUARDED = (
    (
        '<t t-if="object.carrier_tracking_url">',
        (
            "<t t-if=\"hasattr(object, 'carrier_tracking_url') and"
            ' object.carrier_tracking_url">'
        ),
    ),
    (
        't-value="object.get_multiple_carrier_tracking()"',
        (
            "t-value=\"hasattr(object, 'get_multiple_carrier_tracking') and"
            ' object.get_multiple_carrier_tracking()"'
        ),
    ),
)


def migrate(cr, version):
    cr.execute(
        """
        SELECT res_id
          FROM ir_model_data
         WHERE module = 'stock'
           AND name = 'mail_template_data_delivery_confirmation'
        """
    )
    row = cr.fetchone()
    if not row:
        return
    template_id = row[0]
    cr.execute("SELECT body_html FROM mail_template WHERE id = %s", [template_id])
    row = cr.fetchone()
    if not row or not row[0]:
        return
    body_by_lang = row[0]
    changed = False
    for lang, body in body_by_lang.items():
        if not body:
            continue
        for old, new in UNGUARDED:
            if old in body:
                body = body.replace(old, new)
                changed = True
        body_by_lang[lang] = body
    if not changed:
        return
    cr.execute(
        "UPDATE mail_template SET body_html = %s WHERE id = %s",
        [Json(body_by_lang), template_id],
    )
    _logger.info(
        "stock: guarded the delivery-only attributes in the delivery confirmation"
        " template body."
    )
