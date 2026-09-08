import logging

_logger = logging.getLogger(__name__)

FLIP = """
    UPDATE pos_order_line
       SET price_subtotal = -price_subtotal,
           price_subtotal_incl = -price_subtotal_incl
     WHERE qty <> 0
       AND price_unit <> 0
       AND price_subtotal <> 0
       AND SIGN(price_subtotal) <> SIGN(qty) * SIGN(price_unit)
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute(FLIP)
    _logger.info(
        "pos.order.line: signed %s subtotal(s) that disagreed with their quantity",
        cr.rowcount,
    )
