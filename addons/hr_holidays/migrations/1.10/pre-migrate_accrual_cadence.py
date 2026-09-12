import logging

from odoo.db.schema import column_exists, create_column
from odoo.tools import SQL
from odoo.tools.module_data import rename_field

_logger = logging.getLogger(__name__)

MODEL = "hr.leave.accrual.level"
TABLE = "hr_leave_accrual_level"

# `frequency` stored three things in one value: the period, whether the period has
# a second anchor, and whether the added value is per period or per hour. They are
# `mixin.recurrence.anchored`'s `repeat_unit` and `repeat_twice` and the level's own
# `accrual_basis` now; `frequency` is derived from them and no longer stored.
# `worked_hours` is hr_holidays_attendance's value and is mapped here because this
# migration runs first and the column is plain text until that module loads.
_CADENCE = {
    "hourly": ("day", False, "hour"),
    "daily": ("day", False, "period"),
    "weekly": ("week", False, "period"),
    "bimonthly": ("month", True, "period"),
    "monthly": ("month", False, "period"),
    "biyearly": ("year", True, "period"),
    "yearly": ("year", False, "period"),
    "worked_hours": ("day", False, "worked_hour"),
}
_WEEKDAYS = {
    "0": "MON",
    "1": "TUE",
    "2": "WED",
    "3": "THU",
    "4": "FRI",
    "5": "SAT",
    "6": "SUN",
}


def migrate(cr, version):
    if not version or not column_exists(cr, TABLE, "frequency"):
        return

    # One-to-one renames keep their ir.model.fields ids, and with them any export
    # template or tracking value pointing at them.
    rename_field(cr, MODEL, "week_day", "repeat_weekday", values=_WEEKDAYS)
    rename_field(cr, MODEL, "first_day", "repeat_day")
    rename_field(cr, MODEL, "second_day", "repeat_second_day")
    rename_field(cr, MODEL, "first_month", "repeat_month")
    rename_field(cr, MODEL, "second_month", "repeat_second_month")

    for column, sql_type in (
        ("repeat_unit", "varchar"),
        ("repeat_twice", "bool"),
        ("accrual_basis", "varchar"),
    ):
        if not column_exists(cr, TABLE, column):
            create_column(cr, TABLE, column, sql_type)

    for frequency, (unit, twice, basis) in _CADENCE.items():
        cr.execute(
            SQL(
                "UPDATE %s SET repeat_unit = %s, repeat_twice = %s, accrual_basis = %s"
                " WHERE frequency = %s",
                SQL.identifier(TABLE),
                unit,
                twice,
                basis,
                frequency,
            )
        )
        if cr.rowcount:
            _logger.info(
                "hr_holidays 1.10: %d accrual level(s) with frequency %s now"
                " repeat every %s%s, accruing per %s.",
                cr.rowcount,
                frequency,
                unit,
                " twice" if twice else "",
                basis.replace("_", " "),
            )

    # The anchor day and month were three separate columns depending on the
    # frequency -- first_day for a month, first_month_day for twice a year,
    # yearly_day/yearly_month for once a year. They are one pair now.
    if column_exists(cr, TABLE, "first_month_day"):
        cr.execute(
            SQL(
                "UPDATE %s SET repeat_day = first_month_day,"
                " repeat_second_day = second_month_day WHERE frequency = 'biyearly'",
                SQL.identifier(TABLE),
            )
        )
    if column_exists(cr, TABLE, "yearly_day"):
        cr.execute(
            SQL(
                "UPDATE %s SET repeat_day = yearly_day, repeat_month = yearly_month"
                " WHERE frequency = 'yearly'",
                SQL.identifier(TABLE),
            )
        )
    cr.execute(
        SQL(
            "UPDATE %s SET repeat_unit = 'day', repeat_twice = FALSE,"
            " accrual_basis = 'period' WHERE repeat_unit IS NULL",
            SQL.identifier(TABLE),
        )
    )
    if cr.rowcount:
        _logger.warning(
            "hr_holidays 1.10: %d accrual level(s) had no known frequency and"
            " default to daily, per period.",
            cr.rowcount,
        )

    # The superseded columns go with the value they were read by: first_month_day,
    # second_month_day, yearly_day and yearly_month are no longer fields, and
    # frequency is no longer stored, so the ORM would leave all five behind.
    for column in (
        "first_month_day",
        "second_month_day",
        "yearly_day",
        "yearly_month",
        "frequency",
    ):
        cr.execute(
            SQL(
                "ALTER TABLE %s DROP COLUMN IF EXISTS %s",
                SQL.identifier(TABLE),
                SQL.identifier(column),
            )
        )
