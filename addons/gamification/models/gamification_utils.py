"""Shared utility functions for the gamification module."""

from datetime import date, timedelta

from dateutil.relativedelta import MO, relativedelta


def start_end_date_for_period(
    period: str,
    default_start_date: date | bool = False,
    default_end_date: date | bool = False,
) -> tuple[date | bool, date | bool]:
    """Return the start and end date for a goal period based on today.

    :param period: one of 'daily', 'weekly', 'monthly', 'yearly', 'once'.
    :param default_start_date: fallback start date for 'once' period.
    :param default_end_date: fallback end date for 'once' period.
    :return: ``(start_date, end_date)`` as date objects, or ``False`` if
        the period is 'once' and no defaults are provided.
    """
    today = date.today()
    if period == "daily":
        start_date = today
        end_date = today
    elif period == "weekly":
        start_date = today + relativedelta(weekday=MO(-1))
        end_date = start_date + timedelta(days=6)
    elif period == "monthly":
        start_date = today.replace(day=1)
        end_date = today + relativedelta(months=1, day=1, days=-1)
    elif period == "yearly":
        start_date = today.replace(month=1, day=1)
        end_date = today.replace(month=12, day=31)
    else:  # period == 'once'
        return (default_start_date, default_end_date)

    return (start_date, end_date)
