import logging

_logger = logging.getLogger(__name__)

SUFFIX = ".stock_valuation_closing_ids"


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT key, value FROM ir_config_parameter WHERE key LIKE %s",
        [f"%{SUFFIX}"],
    )
    rows = cr.fetchall()
    if not rows:
        return

    move_ids = set()
    keys = []
    for key, value in rows:
        keys.append(key)
        for chunk in (value or "").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                move_ids.add(int(chunk))

    if move_ids:
        cr.execute(
            "UPDATE account_move SET is_stock_valuation_closing = TRUE WHERE id = ANY(%s)",
            [sorted(move_ids)],
        )
        _logger.info(
            "stock_account: flagged %s existing inventory valuation closing entries",
            cr.rowcount,
        )
    cr.execute("DELETE FROM ir_config_parameter WHERE key = ANY(%s)", [keys])
