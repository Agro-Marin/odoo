__all__ = [
    "WEEKDAY_NUMBER",
    "Granularity",
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

import calendar
import math
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Any, Literal

from dateutil.relativedelta import relativedelta, weekdays

from odoo.libs.numbers.float_utils import float_round

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    import babel

utc = UTC

WEEKDAY_NUMBER = dict(
    zip(
        (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ),
        range(7),
        strict=True,
    )
)

Granularity = Literal["year", "quarter", "month", "week", "day", "hour"]


def float_to_time(hours: float) -> time:
    if not 0.0 <= hours <= 24.0:
        msg = f"hours must be a number in [0.0, 24.0], got {hours!r}"
        raise ValueError(msg)
    if hours == 24.0:  # noqa: RUF069  exact boundary: 24.0 is representable and the range is already checked
        return time.max
    fractional, integral = math.modf(hours)
    minutes = int(float_round(60 * fractional, precision_digits=0))
    if minutes == 60:
        integral += 1
        minutes = 0
    if integral >= 24:
        return time.max
    return time(int(integral), minutes, 0)


def time_to_float(duration: time | timedelta) -> float:
    if isinstance(duration, timedelta):
        return duration.total_seconds() / 3600
    if duration == time.max:
        return 24.0
    seconds = duration.microsecond / 1_000_000 + duration.second + duration.minute * 60
    return seconds / 3600 + duration.hour


def localized(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=utc)


def to_timezone(tz: tzinfo | None) -> Callable[[datetime], datetime]:
    if tz is None:
        return lambda dt: dt.astimezone(utc).replace(tzinfo=None)
    return lambda dt: dt.astimezone(tz)


def parse_iso_date(value: str) -> date | datetime:
    if len(value) <= 10:
        return date.fromisoformat(value)
    now = datetime.fromisoformat(value)
    if now.tzinfo is not None:
        raise ValueError(f"expecting only datetimes with no timezone: {value!r}")
    return now


def get_month[D: (date, datetime)](date: D) -> tuple[D, D]:
    return date.replace(day=1), date.replace(
        day=calendar.monthrange(date.year, date.month)[1]
    )


def get_quarter_number(date: date) -> int:
    return (date.month - 1) // 3 + 1


def get_quarter[D: (date, datetime)](date: D) -> tuple[D, D]:
    month_from = (date.month - 1) // 3 * 3 + 1
    date_from = date.replace(month=month_from, day=1)
    date_to = date_from.replace(month=month_from + 2)
    date_to = date_to.replace(day=calendar.monthrange(date_to.year, date_to.month)[1])
    return date_from, date_to


def get_fiscal_year[D: (date, datetime)](
    date: D, day: int = 31, month: int = 12
) -> tuple[D, D]:

    def fix_day(year: int, month: int, day: int) -> int:
        max_day = calendar.monthrange(year, month)[1]
        if month == 2 and day in (28, max_day):
            return max_day
        return min(day, max_day)

    date_to = date.replace(month=month, day=fix_day(date.year, month, day))

    if date <= date_to:
        date_from = date_to - relativedelta(years=1)
        day = fix_day(date_from.year, date_from.month, date_from.day)
        date_from = date_from.replace(day=day)
        date_from += relativedelta(days=1)
    else:
        date_from = date_to + relativedelta(days=1)
        date_to += relativedelta(years=1)
        day = fix_day(date_to.year, date_to.month, date_to.day)
        date_to = date_to.replace(day=day)
    return date_from, date_to


def get_timedelta(
    qty: int,
    granularity: Literal["hour", "day", "week", "month", "year"],
) -> relativedelta:
    switch = {
        "hour": relativedelta(hours=qty),
        "day": relativedelta(days=qty),
        "week": relativedelta(weeks=qty),
        "month": relativedelta(months=qty),
        "year": relativedelta(years=qty),
    }
    return switch[granularity]


def start_of[D: (date, datetime)](value: D, granularity: Granularity) -> D:
    if granularity == "year":
        result = value.replace(month=1, day=1)
    elif granularity == "quarter":
        result = get_quarter(value)[0]
    elif granularity == "month":
        result = value.replace(day=1)
    elif granularity == "week":
        result = value - relativedelta(
            days=calendar.weekday(value.year, value.month, value.day)
        )
    elif granularity == "day":
        result = value
    elif granularity == "hour" and isinstance(value, datetime):
        return datetime.combine(value, time.min, value.tzinfo).replace(hour=value.hour)
    elif isinstance(value, datetime):
        raise ValueError(
            f"Granularity must be year, quarter, month, week, day or hour for value {value}"
        )
    else:
        raise ValueError(
            f"Granularity must be year, quarter, month, week or day for value {value}"
        )

    if isinstance(value, datetime):
        return datetime.combine(result, time.min, value.tzinfo)
    return result


def end_of[D: (date, datetime)](value: D, granularity: Granularity) -> D:
    if granularity == "year":
        result = value.replace(month=12, day=31)
    elif granularity == "quarter":
        result = get_quarter(value)[1]
    elif granularity == "month":
        result = value + relativedelta(day=1, months=1, days=-1)
    elif granularity == "week":
        result = value + relativedelta(
            days=6 - calendar.weekday(value.year, value.month, value.day)
        )
    elif granularity == "day":
        result = value
    elif granularity == "hour" and isinstance(value, datetime):
        return datetime.combine(value, time.max, value.tzinfo).replace(hour=value.hour)
    elif isinstance(value, datetime):
        raise ValueError(
            f"Granularity must be year, quarter, month, week, day or hour for value {value}"
        )
    else:
        raise ValueError(
            f"Granularity must be year, quarter, month, week or day for value {value}"
        )

    if isinstance(value, datetime):
        return datetime.combine(result, time.max, value.tzinfo)
    return result


def add[D: (date, datetime)](value: D, *args: int, **kwargs: int) -> D:
    return value + relativedelta(*args, **kwargs)


def subtract[D: (date, datetime)](value: D, *args: int, **kwargs: int) -> D:
    return value - relativedelta(*args, **kwargs)


def date_range[D: (date, datetime)](
    start: D, end: D, step: relativedelta = relativedelta(months=1)
) -> Iterator[D]:
    restore_tz: tzinfo | None = None

    if isinstance(start, datetime) and isinstance(end, datetime):
        are_naive = start.tzinfo is None and end.tzinfo is None
        are_utc = start.tzinfo == utc and end.tzinfo == utc

        are_others = start.tzinfo and end.tzinfo and not are_utc

        if are_others:
            start_key = getattr(start.tzinfo, "key", None) or getattr(
                start.tzinfo, "zone", None
            )
            end_key = getattr(end.tzinfo, "key", None) or getattr(
                end.tzinfo, "zone", None
            )
            if start_key != end_key:
                msg = "Timezones of start argument and end argument seem inconsistent"
                raise ValueError(msg)

        if not are_naive and not are_utc and not are_others:
            msg = "Timezones of start argument and end argument mismatch"
            raise ValueError(msg)

        if not are_naive:
            restore_tz = start.tzinfo
            start = start.replace(tzinfo=None)
            end = end.replace(tzinfo=None)

    elif isinstance(start, date) and isinstance(end, date):
        if not isinstance(start + step, date):
            msg = "the step interval must add only entire days"
            raise ValueError(msg)
    else:
        msg = "start/end should be both date or both datetime type"
        raise ValueError(msg)

    if start > end:
        msg = "start > end, start date must be before end"
        raise ValueError(msg)

    if start >= start + step:
        msg = "Looks like step is null or negative"
        raise ValueError(msg)

    while start <= end:
        if restore_tz is not None and isinstance(start, datetime):
            yield start.replace(tzinfo=restore_tz)
        else:
            yield start
        start += step


def sum_intervals(intervals: Iterable[tuple[datetime, datetime, Any]]) -> float:
    return sum(
        (interval[1] - interval[0]).total_seconds() / 3600 for interval in intervals
    )


def weeknumber(
    locale: babel.Locale, date: date, first_week_day: int | None = None
) -> tuple[int, int]:
    if first_week_day is None:
        first_week_day = locale.first_week_day
    if first_week_day == 0 and locale.min_week_days == 4:
        return date.isocalendar()[:2]

    delta = relativedelta(weekday=weekdays[first_week_day](-1))
    fdny = date.replace(year=date.year + 1, month=1, day=1) - delta
    if date >= fdny:
        return date.year + 1, 1

    fdow = date.replace(month=1, day=1) - delta
    doy = (date - fdow).days

    return date.year, (doy // 7 + 1)


def weekstart(locale: babel.Locale, date: date) -> date:
    return date + relativedelta(weekday=weekdays[locale.first_week_day](-1))


def weekend(locale: babel.Locale, date: date) -> date:
    return weekstart(locale, date) + relativedelta(days=6)
