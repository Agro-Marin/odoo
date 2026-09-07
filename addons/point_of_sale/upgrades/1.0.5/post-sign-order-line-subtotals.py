import logging

_logger = logging.getLogger(__name__)

# `pos.order.line.price_subtotal` used to be a magnitude on an order flagged
# `is_refund` and signed everywhere else, so two lines of identical economic
# value were stored `+200` and `-100`. It now always carries the sign of `qty`,
# like `total_cost` and `pos.order.amount_total`.
#
# The repair is the expression `pos_order_report`'s SQL view used to apply on
# every read, applied once at rest instead: a row whose stored sign disagrees
# with `SIGN(qty) * SIGN(price_unit)` is flipped. That view no longer launders,
# so its figures are unchanged by this migration -- it was already reporting the
# signed value.
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
