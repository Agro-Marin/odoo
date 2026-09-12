# Two shapes of schedule. A cadence is every N units from a start: below a day
# it steps exact elapsed time, from a day up it steps local wall time, so a
# daily 02:00 job stays at 02:00 across a DST change. An anchored schedule is
# fixed points inside a period, and a day past the end of a short month is
# clamped to its last day -- what leave accrual has always done, and what
# iCalendar's BYMONTHDAY does not: it skips the month instead.

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

from dateutil.relativedelta import relativedelta

from .date_utils import TimeUnit, get_timedelta

_EXACT_UNITS: dict[TimeUnit, str] = {"minute": "minutes", "hour": "hours"}
_ANCHOR_UNITS = frozenset({"day", "week", "month", "year"})


def next_after[D: (date, datetime)](
    start: D,
    after: D,
    interval: int,
    unit: TimeUnit,
    tz: tzinfo | None = None,
) -> D:
    if interval <= 0:
        msg = f"interval must be positive, got {interval}"
        raise ValueError(msg)
    if start > after:
        return start
    if unit in _EXACT_UNITS:
        step = timedelta(**{_EXACT_UNITS[unit]: interval})
        return start + ((after - start) // step + 1) * step

    # Each occurrence is start + k units, never the previous one + 1 unit: a
    # series started on the 31st lands on the 28th in February and back on the
    # 31st in March, instead of staying on the 28th for good.
    delta = get_timedelta(interval, unit)
    local_start = (
        start.replace(tzinfo=UTC).astimezone(tz)
        if tz is not None and isinstance(start, datetime)
        else start
    )
    k = 1
    while True:
        candidate = local_start + delta * k
        if tz is not None and isinstance(candidate, datetime):
            candidate = candidate.astimezone(UTC).replace(tzinfo=None)
        if candidate > after:
            return candidate
        k += 1


@dataclass(frozen=True, slots=True)
class Anchor:
    day: int | None = None
    month: int | None = None
    weekday: int | None = None


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _period_occurrences(
    reference: date, unit: str, anchors: Sequence[Anchor], shift: int
) -> list[date]:
    if unit == "week":
        monday = (
            reference - timedelta(days=reference.weekday()) + timedelta(weeks=shift)
        )
        return sorted({monday + timedelta(days=_require(a.weekday)) for a in anchors})
    if unit == "month":
        first = reference.replace(day=1) + relativedelta(months=shift)
        return sorted(
            {_clamped(first.year, first.month, _require(a.day)) for a in anchors}
        )
    year = reference.year + shift
    return sorted({_clamped(year, _require(a.month), _require(a.day)) for a in anchors})


def _require(value: int | None) -> int:
    if value is None:
        msg = "anchor is missing the component its period needs"
        raise ValueError(msg)
    return value


def _check_anchored(unit: str, anchors: Sequence[Anchor]) -> None:
    if unit not in _ANCHOR_UNITS:
        msg = f"anchored schedules have a day, week, month or year period, not {unit!r}"
        raise ValueError(msg)
    if unit != "day" and not anchors:
        msg = f"a {unit} schedule needs at least one anchor"
        raise ValueError(msg)


def next_anchor(after: date, unit: str, anchors: Sequence[Anchor]) -> date:
    _check_anchored(unit, anchors)
    if unit == "day":
        return after + timedelta(days=1)
    for shift in (0, 1):
        for occurrence in _period_occurrences(after, unit, anchors, shift):
            if occurrence > after:
                return occurrence
    msg = "an anchored schedule has an occurrence in every period"
    raise AssertionError(msg)


def previous_anchor(on: date, unit: str, anchors: Sequence[Anchor]) -> date:
    _check_anchored(unit, anchors)
    if unit == "day":
        return on
    for shift in (0, -1):
        for occurrence in reversed(_period_occurrences(on, unit, anchors, shift)):
            if occurrence <= on:
                return occurrence
    msg = "an anchored schedule has an occurrence in every period"
    raise AssertionError(msg)
