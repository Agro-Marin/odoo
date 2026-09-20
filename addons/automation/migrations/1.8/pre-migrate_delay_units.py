from odoo.tools import SQL

# A rule's trigger delay and a Wait step's pause take the shared singular time units,
# measured by `get_timedelta`. The trigger delay already spelled three of its four
# units that way and the minute in the plural; the Wait step spelled all three in
# the plural, as `datetime.timedelta` keywords.
_UPDATES = (
    ("automation_rule", "trg_date_range_type", {"minutes": "minute"}),
    (
        "ir_act_server",
        "wait_unit",
        {"minutes": "minute", "hours": "hour", "days": "day"},
    ),
)


def migrate(cr, version):
    if not version:
        return
    for table, column, units in _UPDATES:
        for plural, singular in units.items():
            cr.execute(
                SQL(
                    "UPDATE %s SET %s = %s WHERE %s = %s",
                    SQL.identifier(table),
                    SQL.identifier(column),
                    singular,
                    SQL.identifier(column),
                    plural,
                )
            )
