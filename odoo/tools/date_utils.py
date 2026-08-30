import re
import typing
from datetime import UTC, date, datetime, timedelta
from typing import Any

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
# Keyed by the SINGULAR relativedelta field `=` sets, so every key here has to be
# one relativedelta accepts.  "week" was not -- relativedelta takes `weeks`, not
# `week` -- so the only path that could read it was `=Nw`, which raised TypeError
# and surfaced as "Invalid term". Nothing documents or tests `=Nw`; the entry was
# describing a spelling that never worked.
_TRUNCATE_UNIT = {
    "day": _TRUNCATE_TODAY,
    "month": _TRUNCATE_TODAY,
    "year": _TRUNCATE_TODAY,
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


def _apply_weekday_term(
    dt: datetime | date, operator: str, dayname: str, week_start: int
) -> datetime | date:
    """Move `dt` to the named weekday, in the direction `operator` asks for."""
    weekday = week_start if dayname == "week_start" else WEEKDAY_NUMBER[dayname]
    offset = ((weekday - week_start) % 7) - ((dt.weekday() - week_start) % 7)
    if operator == "+":
        if offset < 0:
            offset += 7
    elif operator == "-":
        if offset > 0:
            offset -= 7
    elif isinstance(dt, datetime):
        # "=monday" means *that* weekday at midnight, not this instant on it
        dt += _TRUNCATE_TODAY
    return dt + timedelta(offset)


def _apply_unit_term(dt: datetime | date, operator: str, term: str) -> datetime | date:
    """Add, subtract or set the unit `term` names (`+3d`, `-2w`, `=5H`)."""
    unit = _SHORT_DATE_UNIT[term[-1]]
    if operator in ("+", "-"):
        number = int(term[:-1])
    else:
        # a singular relativedelta key SETS the field rather than shifting it
        number = int(term[1:-1])
        unit = unit.removesuffix("s")
        if unit not in _TRUNCATE_UNIT:
            raise ValueError(f"{term[-1]!r} cannot be set with '='; use '+' or '-'")
        if isinstance(dt, datetime):
            dt += _TRUNCATE_UNIT[unit]
    return dt + relativedelta(**{unit: number})


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
        # a `date` for now -- a time-valued term below can promote it back to a
        # naive datetime; see the note above the return
        dt = Date.context_today(env["base"], dt)
    else:
        assert isinstance(dt, datetime)
        dt = Datetime.context_timestamp(env["base"], dt)

    week_start: int | None = None  # read at most once, on the first weekday term

    for term in terms:
        operator = term[0]
        if operator not in ("+", "-", "=") or len(term) < 3:
            raise ValueError(f"Invalid term {term!r} in expression date: {value!r}")

        dayname = term[1:]
        if dayname in WEEKDAY_NUMBER or dayname == "week_start":
            if week_start is None:
                res_lang: Any = env["res.lang"]
                week_start = (
                    int(res_lang._get_data(code=env.user.lang).week_start) - 1  # type: ignore[attr-defined]
                )
            dt = _apply_weekday_term(dt, operator, dayname, week_start)
            continue

        try:
            dt = _apply_unit_term(dt, operator, term)
        except ValueError, TypeError, KeyError:
            raise ValueError(
                f"Invalid term {term!r} in expression date: {value!r}"
            ) from None

    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        elif started_as_date:
            # Reachable, and not obviously so.  "today" makes dt a plain `date`
            # (Date.context_today returns today.date()), but relativedelta
            # PROMOTES a date to a naive datetime as soon as a time component is
            # set: date(2024,1,5) + relativedelta(hour=5) is datetime(2024,1,5,5).
            # So "today =5H" arrives here naive and still in the user's zone, and
            # skipping this conversion shifts it by the offset -- 04:00 read as
            # 05:00 for a UTC+1 user, which is what test_parse_date_relative_tz
            # pins.
            dt = (
                dt.replace(tzinfo=env["base"].env.tz)
                .astimezone(UTC)
                .replace(tzinfo=None)
            )
    return dt
