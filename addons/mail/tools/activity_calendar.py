__all__ = [
    "ANCHOR_MINUTES",
    "days_by_timezone",
    "days_elsewhere",
    "state_for",
    "today_by_tz",
    "today_in_tz",
    "tz_anchor",
]

import functools
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal

from odoo.libs.datetime import all_timezones, timezone

ANCHOR_MINUTES = 15


@functools.lru_cache(maxsize=4)
def days_by_timezone(anchor: datetime) -> tuple[tuple[date, tuple[str, ...]], ...]:
    days = defaultdict(list)
    for tz_name in all_timezones():
        days[anchor.astimezone(timezone(tz_name)).date()].append(tz_name)
    return tuple((day, tuple(names)) for day, names in days.items())


def tz_anchor(moment: datetime) -> datetime:
    return moment.replace(
        minute=moment.minute // ANCHOR_MINUTES * ANCHOR_MINUTES,
        second=0,
        microsecond=0,
    )


def today_in_tz(
    tz: str | Literal[False] = False, moment: datetime | None = None
) -> date:
    moment = moment or datetime.now(UTC)
    if not tz or tz not in all_timezones():
        return moment.date()
    return moment.astimezone(timezone(tz)).date()


def today_by_tz(
    tzs: Iterable[str | Literal[False]], moment: datetime | None = None
) -> dict[str | Literal[False], date]:
    moment = moment or datetime.now(UTC)
    return {tz: today_in_tz(tz, moment) for tz in set(tzs)}


def state_for(date_deadline: date, today: date) -> str:
    if date_deadline == today:
        return "today"
    return "overdue" if date_deadline < today else "planned"


def days_elsewhere(
    moment: datetime | None = None,
) -> list[tuple[date, tuple[str, ...]]]:
    moment = moment or datetime.now(UTC)
    fallback = today_in_tz(False, moment)
    return [
        (day, names)
        for day, names in days_by_timezone(tz_anchor(moment))
        if day != fallback
    ]
