from odoo.tools import SQL

# A mail scheduler's offset takes the shared singular time units, measured by
# `get_timedelta`; "now" stays its own value. Both concrete schedulers store it.
_UNITS = {"hours": "hour", "days": "day", "weeks": "week", "months": "month"}


def migrate(cr, version):
    if not version:
        return
    for table in ("event_mail", "event_type_mail"):
        for plural, singular in _UNITS.items():
            cr.execute(
                SQL(
                    "UPDATE %s SET interval_unit = %s WHERE interval_unit = %s",
                    SQL.identifier(table),
                    singular,
                    plural,
                )
            )
