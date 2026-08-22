import functools
import typing
from datetime import UTC, date, datetime, time
from typing import override

from odoo.libs.datetime import TIMEZONE_ALIASES, all_timezones, utc
from odoo.libs.datetime import timezone as get_timezone
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DATE_FORMAT
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT
from odoo.tools import SQL, date_utils

from ..constants import READ_GROUP_NUMBER_GRANULARITY
from ..parsing import parse_field_expr
from .base import Field, _logger, _make_scalar_get


@functools.cache
def _get_all_timezones_set() -> frozenset[str]:
    return frozenset(all_timezones())


_sql_timezones_set: dict[str, frozenset[str]] = {}


def _get_sql_timezones_set(env) -> frozenset[str]:
    names = _sql_timezones_set.get(env.cr.dbname)
    if names is None:
        env.cr.execute("SELECT name FROM pg_timezone_names")
        names = frozenset(name for [name] in env.cr.fetchall())
        _sql_timezones_set[env.cr.dbname] = names
    return names


def _sql_timezone_name(env, tz_name: str) -> str | None:
    """The name PostgreSQL accepts for ``tz_name``, or None if it has none.

    Refusing a name outright and grouping in UTC is a wrong answer, not a safe
    one: an 'Asia/Calcutta' user reading a month group-by silently gets buckets
    cut 5h30 away from their own midnight. 99 of the 113 names this PostgreSQL
    refuses are only legacy spellings of names it does know, so the alias is
    resolved first and UTC is left for the 14 that genuinely have no server-side
    equivalent.
    """
    sql_names = _get_sql_timezones_set(env)
    if tz_name in sql_names:
        return tz_name
    canonical = TIMEZONE_ALIASES.get(tz_name)
    if canonical is not None and canonical in sql_names:
        return canonical
    return None


if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.tools import Query

    from .._typing import ModelLike
    from ..models import BaseModel

DATE_LENGTH = len(date.today().strftime(DATE_FORMAT))
DATETIME_LENGTH = len(datetime.now().strftime(DATETIME_FORMAT))


class BaseDate[T](Field[T | typing.Literal[False]]):
    is_temporal = True

    start_of = staticmethod(date_utils.start_of)
    end_of = staticmethod(date_utils.end_of)
    add = staticmethod(date_utils.add)
    subtract = staticmethod(date_utils.subtract)

    def expression_getter(self, field_expr: str) -> Callable[[BaseModel], typing.Any]:
        _fname, property_name = parse_field_expr(field_expr)
        if not property_name:
            return super().expression_getter(field_expr)

        get_value = self.__get__
        get_property = self._expression_property_getter(property_name)
        return lambda record: (value := get_value(record)) and get_property(value)

    def _expression_property_getter(
        self, property_name: str
    ) -> Callable[[T], typing.Any]:
        match property_name:
            case "tz":
                return lambda value: value
            case "year_number":
                return lambda value: value.year
            case "quarter_number":
                return lambda value: (value.month - 1) // 3 + 1
            case "month_number":
                return lambda value: value.month
            case "iso_week_number":
                return lambda value: value.isocalendar().week
            case "day_of_year":
                return lambda value: value.timetuple().tm_yday
            case "day_of_month":
                return lambda value: value.day
            case "day_of_week":
                return lambda value: value.isoweekday() % 7
            case "hour_number" if self.type == "datetime":
                return lambda value: value.hour
            case "minute_number" if self.type == "datetime":
                return lambda value: value.minute
            case "second_number" if self.type == "datetime":
                return lambda value: value.second
            case "hour_number" | "minute_number" | "second_number":
                return lambda value: 0
        assert property_name not in READ_GROUP_NUMBER_GRANULARITY, (
            f"Property not implemented {property_name}"
        )
        raise ValueError(
            f"Error when processing the granularity {property_name} is not supported. "
            f"Only {', '.join(READ_GROUP_NUMBER_GRANULARITY.keys())} are supported"
        )

    def property_to_sql(
        self,
        field_sql: SQL,
        property_name: str,
        model: ModelLike,
        alias: str,
        query: Query,
    ) -> SQL:
        sql_expr = field_sql
        if self.type == "datetime" and (tz_name := model.env.context.get("tz")):
            if sql_tz := _sql_timezone_name(model.env, tz_name):
                sql_expr = SQL(
                    "timezone(%s, timezone('UTC', %s))",
                    SQL.literal(sql_tz),
                    sql_expr,
                )
            else:
                _logger.warning(
                    "Grouping in UTC: the database does not know timezone %r", tz_name
                )
        if property_name == "tz":
            return sql_expr
        if property_name not in READ_GROUP_NUMBER_GRANULARITY:
            raise ValueError(
                f"Error when processing the granularity {property_name} is not supported. Only {', '.join(READ_GROUP_NUMBER_GRANULARITY.keys())} are supported"
            )
        granularity = READ_GROUP_NUMBER_GRANULARITY[property_name]
        return SQL("date_part('%s', %%s)" % granularity, sql_expr)

    @override
    def convert_to_column(
        self,
        value,
        record: ModelLike,
        values: dict | None = None,
        validate: bool = True,
    ) -> typing.Any:
        return self.convert_to_cache(value, record, validate=validate)


class Date(BaseDate[date]):
    type = "date"
    _column_type = ("date", "date")

    if not typing.TYPE_CHECKING:
        __get__ = _make_scalar_get(lambda v: False if v is None else v)

    @staticmethod
    def today(*args) -> date:
        return date.today()

    @staticmethod
    def context_today(
        record: BaseModel, timestamp: date | datetime | None = None
    ) -> date:
        today = timestamp or datetime.now()
        tz = record.env.tz
        today_utc = today.replace(tzinfo=utc)
        today = today_utc.astimezone(tz)
        return today.date()

    @staticmethod
    def to_date(
        value: str | date | datetime | typing.Literal[False] | None,
    ) -> date | None:
        if not value:
            return None
        if isinstance(value, date):
            if isinstance(value, datetime):
                return value.date()
            return value
        if not isinstance(value, str):
            raise TypeError(f"expected str or date, got {value!r}")
        value = value[:DATE_LENGTH]
        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.strptime(value, DATE_FORMAT).date()

    from_string = to_date

    @staticmethod
    def to_string(
        value: date | typing.Literal[False],
    ) -> str | typing.Literal[False]:
        return value.strftime(DATE_FORMAT) if value else False

    @override
    def convert_to_cache(
        self, value, record: ModelLike, validate: bool = True
    ) -> typing.Any:
        if not value:
            return None
        return self.to_date(value)

    @override
    def convert_to_export(self, value: typing.Any, record: ModelLike) -> typing.Any:
        return self.to_date(value) or ""

    @override
    def convert_to_display_name(
        self, value: typing.Any, record: ModelLike
    ) -> str | typing.Literal[False]:
        return Date.to_string(value)


class Datetime(BaseDate[datetime]):
    type = "datetime"
    _column_type = ("timestamp", "timestamp")

    if not typing.TYPE_CHECKING:
        __get__ = _make_scalar_get(lambda v: False if v is None else v)

    @staticmethod
    def now(*args) -> datetime:
        return datetime.now().replace(microsecond=0)

    @staticmethod
    def today(*args) -> datetime:
        return Datetime.now().replace(hour=0, minute=0, second=0)

    @staticmethod
    def context_timestamp(record: ModelLike, timestamp: datetime) -> datetime:
        assert isinstance(timestamp, datetime), "Datetime instance expected"
        tz = record.env.tz
        utc_timestamp = timestamp.replace(tzinfo=utc)
        return utc_timestamp.astimezone(tz)

    @staticmethod
    def to_datetime(
        value: str | date | datetime | typing.Literal[False] | None,
    ) -> datetime | None:
        if not value:
            return None
        if isinstance(value, date):
            if isinstance(value, datetime):
                if value.tzinfo:
                    if value.tzinfo is UTC or value.tzinfo == UTC:
                        return value.replace(tzinfo=None)
                    return value.astimezone(UTC).replace(tzinfo=None)
                return value
            return datetime.combine(value, time.min)

        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            value = datetime.strptime(value[:DATETIME_LENGTH], DATETIME_FORMAT)
        if value.tzinfo:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    from_string = to_datetime

    @staticmethod
    def to_string(
        value: datetime | typing.Literal[False],
    ) -> str | typing.Literal[False]:
        return value.strftime(DATETIME_FORMAT) if value else False

    def expression_getter(self, field_expr: str) -> Callable[[BaseModel], typing.Any]:
        if field_expr == self.name:
            return self.__get__
        _fname, property_name = parse_field_expr(field_expr)
        get_property = self._expression_property_getter(property_name)

        def getter(record):
            dt = self.__get__(record)
            if not dt:
                return False
            if (
                tz_name := record.env.context.get("tz")
            ) and tz_name in _get_all_timezones_set():
                dt = dt.replace(tzinfo=utc).astimezone(get_timezone(tz_name))
            return get_property(dt)

        return getter

    @override
    def convert_to_cache(
        self, value, record: ModelLike, validate: bool = True
    ) -> typing.Any:
        return self.to_datetime(value)

    @override
    def convert_to_export(self, value: typing.Any, record: ModelLike) -> typing.Any:
        value = self.convert_to_display_name(value, record)
        return self.to_datetime(value) or ""

    @override
    def convert_to_display_name(
        self, value: typing.Any, record: ModelLike
    ) -> str | typing.Literal[False]:
        if not value:
            return False
        return Datetime.to_string(Datetime.context_timestamp(record, value))
