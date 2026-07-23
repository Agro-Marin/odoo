"""ORM SQL/read_group constants: time/number granularity, aggregates, display
formats, and shared ORDER BY fragments.

Kept separate from primitives.py because they depend on dateutil and have a
narrower audience.
"""

from typing import TYPE_CHECKING, Final

import dateutil.relativedelta

from odoo.tools import SQL

if TYPE_CHECKING:
    from collections.abc import Callable

# Time granularity for date grouping (relativedelta intervals)
READ_GROUP_TIME_GRANULARITY: Final[dict[str, dateutil.relativedelta.relativedelta]] = {
    "hour": dateutil.relativedelta.relativedelta(hours=1),
    "day": dateutil.relativedelta.relativedelta(days=1),
    "week": dateutil.relativedelta.relativedelta(days=7),
    "month": dateutil.relativedelta.relativedelta(months=1),
    "quarter": dateutil.relativedelta.relativedelta(months=3),
    "year": dateutil.relativedelta.relativedelta(years=1),
}

# Number granularity for date parts (maps to PostgreSQL date_part functions)
READ_GROUP_NUMBER_GRANULARITY: Final[dict[str, str]] = {
    "year_number": "year",
    "quarter_number": "quarter",
    "month_number": "month",
    "iso_week_number": "week",  # ISO week (only sane week numbering)
    "day_of_year": "doy",
    "day_of_month": "day",
    "day_of_week": "dow",
    "hour_number": "hour",
    "minute_number": "minute",
    "second_number": "second",
}

# Combined time and number granularity
READ_GROUP_ALL_TIME_GRANULARITY: Final[
    dict[str, dateutil.relativedelta.relativedelta | str]
] = READ_GROUP_TIME_GRANULARITY | READ_GROUP_NUMBER_GRANULARITY

# Pre-built SQL constants for ORDER BY — avoids repeated SQL() allocation.
# Shared by the search and read_group SQL builders.
SQL_ORDER_DIR: Final[dict[str, SQL]] = {"ASC": SQL("ASC"), "DESC": SQL("DESC")}
SQL_ORDER_NULLS: Final[dict[str, SQL]] = {
    "NULLS FIRST": SQL("NULLS FIRST"),
    "NULLS LAST": SQL("NULLS LAST"),
}

# Valid SQL aggregation functions for read_group
READ_GROUP_AGGREGATE: Final[dict[str, Callable[[str, SQL], SQL]]] = {
    "sum": lambda table, expr: SQL("SUM(%s)", expr),
    "avg": lambda table, expr: SQL("AVG(%s)", expr),
    "max": lambda table, expr: SQL("MAX(%s)", expr),
    "min": lambda table, expr: SQL("MIN(%s)", expr),
    "bool_and": lambda table, expr: SQL("BOOL_AND(%s)", expr),
    "bool_or": lambda table, expr: SQL("BOOL_OR(%s)", expr),
    "array_agg": lambda table, expr: SQL(
        "ARRAY_AGG(%s ORDER BY %s)", expr, SQL.identifier(table, "id")
    ),
    "array_agg_distinct": lambda table, expr: SQL(
        "(SELECT array_agg(v ORDER BY v) FROM (SELECT DISTINCT unnest(array_agg(%s)) AS v) sub)",
        expr,
    ),
    # 'recordset' aggregates will be post-processed to become recordsets
    "recordset": lambda table, expr: SQL(
        "ARRAY_AGG(%s ORDER BY %s)", expr, SQL.identifier(table, "id")
    ),
    "count": lambda table, expr: SQL("COUNT(%s)", expr),
    "count_distinct": lambda table, expr: SQL("COUNT(DISTINCT %s)", expr),
    # any_value (PG16+): arbitrary non-null value from the group; for fields
    # functionally dependent on the GROUP BY columns, without GROUP BY/MIN/MAX.
    "any_value": lambda table, expr: SQL("ANY_VALUE(%s)", expr),
}


# Display formats for read_group date groupings (Babel format strings).
# Use yyyy (lower) everywhere EXCEPT week-year, which needs YYYY (upper):
# 2006-01-01 is W52 2005 in de_DE but W1 2006 elsewhere, so mixing the two
# (e.g. 'MMM YYYY') yields wrong results like "January 2005".
# Cfr: http://babel.pocoo.org/en/latest/dates.html#date-fields
READ_GROUP_DISPLAY_FORMAT: Final[dict[str, str]] = {
    "hour": "hh:00 dd MMM",
    "day": "dd MMM yyyy",  # yyyy = normal year
    "week": "'W'w YYYY",  # w YYYY = ISO week-year
    "month": "MMMM yyyy",
    "quarter": "QQQ yyyy",
    "year": "yyyy",
}
