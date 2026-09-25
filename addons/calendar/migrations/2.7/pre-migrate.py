from odoo.db import schema


def migrate(cr, version):
    if not version or not schema.table_exists(cr, "calendar_recurrence"):
        return
    # A yearly rule used to repeat on its start date whatever `month_by` said;
    # `day` now means the nth weekday of the start month, so keep the dates
    # these rows already produce.
    cr.execute(
        "UPDATE calendar_recurrence SET month_by = 'date'"
        " WHERE repeat_unit = 'year' AND month_by = 'day'"
    )
