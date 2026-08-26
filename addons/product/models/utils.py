from odoo import tools


def unlink_where_possible(records, delete):
    if not records:
        return records
    try:
        with records.env.cr.savepoint(), tools.mute_logger("odoo.db"):
            delete(records)
    except Exception:
        if len(records) == 1:
            return records
        middle = len(records) // 2
        return unlink_where_possible(records[:middle], delete) | (
            unlink_where_possible(records[middle:], delete)
        )
    return records.browse()
