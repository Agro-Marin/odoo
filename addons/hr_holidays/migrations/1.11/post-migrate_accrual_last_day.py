import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

TABLE = "hr_leave_accrual_level"


# Before 1.11 a day was the only way to ask for the end of a month: the 31st, or a
# yearly month's own length, which the day picker offered and the anchor clamped.
# That day and "last" credit on the same date every period; they differ only in
# where a partial period starts, and "last" is the calendar month that choice
# meant. A day is left alone when the other one of its pair is the 1st of the
# month it would close, because the two would then name one boundary twice.
def _last_day_of(month_column):
    return SQL(
        "EXTRACT(DAY FROM make_date(2024, %s::int, 1)"
        " + INTERVAL '1 month - 1 day')::text",
        SQL.identifier(month_column),
    )


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            """
            UPDATE %(table)s
               SET repeat_day = 'last'
             WHERE (repeat_unit = 'month' AND repeat_day = '31')
                OR (repeat_unit = 'year' AND repeat_day = %(first_last)s
                    AND NOT (repeat_twice AND repeat_second_day = '1'
                             AND repeat_second_month::int = repeat_month::int %% 12 + 1))
            """,
            table=SQL.identifier(TABLE),
            first_last=_last_day_of("repeat_month"),
        )
    )
    first = cr.rowcount
    cr.execute(
        SQL(
            """
            UPDATE %(table)s
               SET repeat_second_day = 'last'
             WHERE repeat_twice
               AND (
                    (repeat_unit = 'month' AND repeat_second_day = '31'
                     AND repeat_day <> '1')
                 OR (repeat_unit = 'year'
                     AND repeat_second_day = %(second_last)s
                     AND NOT (repeat_day = '1'
                              AND repeat_month::int = repeat_second_month::int %% 12 + 1))
               )
            """,
            table=SQL.identifier(TABLE),
            second_last=_last_day_of("repeat_second_month"),
        )
    )
    if first or cr.rowcount:
        _logger.info(
            "hr_holidays 1.11: %d first and %d second accrual day(s) naming the"
            " end of their month now read as the last day.",
            first,
            cr.rowcount,
        )
