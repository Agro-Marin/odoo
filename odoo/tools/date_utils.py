import re
import typing
from datetime import UTC, date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo.libs.datetime import (
    WEEKDAY_NUMBER,
    add,
    date_range,
    end_of,
    float_to_time,
    get_fiscal_year,
    get_month,
    get_quarter,
    get_quarter_number,
    get_timedelta,
    localized,
    parse_iso_date,
    start_of,
    subtract,
    sum_intervals,
    time_to_float,
    to_timezone,
    utc,
    weekend,
    weeknumber,
    weekstart,
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


if typing.TYPE_CHECKING:
    from odoo.orm.runtime import Environment

_TRUNCATE_TODAY = relativedelta(microsecond=0, second=0, minute=0, hour=0)
_TRUNCATE_UNIT = {
    "day": _TRUNCATE_TODAY,
    "month": _TRUNCATE_TODAY,
    "year": _TRUNCATE_TODAY,
    "week": _TRUNCATE_TODAY,
    "hour": relativedelta(microsecond=0, second=0, minute=0),
    "minute": relativedelta(microsecond=0, second=0),
    "second": relativedelta(microsecond=0),
}
_SHORT_DATE_UNIT = {
    "d": "days",
    "m": "months",
    "y": "years",
    "w": "weeks",
    "H": "hours",
    "M": "minutes",
    "S": "seconds",
}

__all__ = [
    "WEEKDAY_NUMBER",
    "add",
    "date_range",
    "end_of",
    "float_to_time",
    "get_fiscal_year",
    "get_month",
    "get_quarter",
    "get_quarter_number",
    "get_timedelta",
    "localized",
    "parse_iso_date",
    "resolve_date",
    "start_of",
    "subtract",
    "sum_intervals",
    "time_to_float",
    "to_timezone",
    "utc",
    "weekend",
    "weeknumber",
    "weekstart",
]


def resolve_date(value: str, env: Environment) -> date | datetime:
    if re.match(r"\d+-", value):
        return parse_iso_date(value)
    terms = value.split()
    if not terms:
        msg = "Empty date value"
        raise ValueError(msg)

    from odoo.orm.fields import Date, Datetime

    dt: datetime | date = Datetime.now()
    term = terms.pop(0) if terms[0] in ("today", "now") else "now"
    started_as_date = term == "today"
    if started_as_date:
        dt = Date.context_today(env["base"], dt)
    else:
        dt = Datetime.context_timestamp(env["base"], dt)

    for term in terms:
        operator = term[0]
        if operator not in ("+", "-", "=") or len(term) < 3:
            raise ValueError(f"Invalid term {term!r} in expression date: {value!r}")

        dayname = term[1:]
        if dayname in WEEKDAY_NUMBER or dayname == "week_start":
            week_start = (
                int(env["res.lang"]._get_data(code=env.user.lang).week_start) - 1
            )
            weekday = week_start if dayname == "week_start" else WEEKDAY_NUMBER[dayname]
            weekday_offset = ((weekday - week_start) % 7) - (
                (dt.weekday() - week_start) % 7
            )
            if operator in ("+", "-"):
                if operator == "+" and weekday_offset < 0:
                    weekday_offset += 7
                elif operator == "-" and weekday_offset > 0:
                    weekday_offset -= 7
            elif isinstance(dt, datetime):
                dt += _TRUNCATE_TODAY
            dt += timedelta(weekday_offset)
            continue

        try:
            unit = _SHORT_DATE_UNIT[term[-1]]
            if operator in ("+", "-"):
                number = int(term[:-1])
            else:
                number = int(term[1:-1])
                unit = unit.removesuffix("s")
                if isinstance(dt, datetime):
                    dt += _TRUNCATE_UNIT[unit]
            dt += relativedelta(**{unit: number})
        except ValueError, TypeError, KeyError:
            raise ValueError(
                f"Invalid term {term!r} in expression date: {value!r}"
            ) from None

    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        elif started_as_date:
            dt = (
                dt.replace(tzinfo=env["base"].env.tz)
                .astimezone(UTC)
                .replace(tzinfo=None)
            )
    return dt
