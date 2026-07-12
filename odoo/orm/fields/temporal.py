import functools
import typing
from datetime import UTC, date, datetime, time
from typing import override

from odoo.libs.datetime import utc
from odoo.libs.datetime.tz import all_timezones
from odoo.libs.datetime.tz import timezone as get_timezone
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DATE_FORMAT
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT
from odoo.tools import SQL, date_utils

from ..constants import READ_GROUP_NUMBER_GRANULARITY
from ..parsing import parse_field_expr
from .base import Field, _logger, _make_scalar_get


@functools.cache
def _get_all_timezones_set() -> frozenset[str]:
    return frozenset(all_timezones())


if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.tools import Query

    from ..models import BaseModel

DATE_LENGTH = len(date.today().strftime(DATE_FORMAT))
DATETIME_LENGTH = len(datetime.now().strftime(DATETIME_FORMAT))


class BaseDate[T](Field[T | typing.Literal[False]]):
    """Common field properties for Date and Datetime."""

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
        """Return a function that maps a field value (date or datetime) to the
        given ``property_name``.
        """
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
                # Match PostgreSQL date_part('dow', …) used by the SQL/read_group
                # path (constants.READ_GROUP_NUMBER_GRANULARITY): Sunday=0..Sat=6.
                # ``tm_wday`` is Monday=0, which made filtered_domain (in-memory)
                # disagree with search on the same ``date.day_of_week`` term.
                return lambda value: value.isoweekday() % 7
            case "hour_number" if self.type == "datetime":
                return lambda value: value.hour
            case "minute_number" if self.type == "datetime":
                return lambda value: value.minute
            case "second_number" if self.type == "datetime":
                return lambda value: value.second
            case "hour_number" | "minute_number" | "second_number":
                # for dates, it is always 0
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
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        sql_expr = field_sql
        if self.type == "datetime" and (tz_name := model.env.context.get("tz")):
            # only use the timezone from the context
            if tz_name in _get_all_timezones_set():
                # Embed the timezone as a SQL literal (not a parameter) so the
                # expression is identical in SELECT and GROUP BY: server-side
                # binding gives each %s a unique $N, which PostgreSQL would
                # otherwise treat as different expressions.
                sql_expr = SQL(
                    "timezone('%s', timezone('UTC', %%s))" % tz_name, sql_expr
                )
            else:
                _logger.warning("Grouping in unknown / legacy timezone %r", tz_name)
        if property_name == "tz":
            # set only the timezone
            return sql_expr
        if property_name not in READ_GROUP_NUMBER_GRANULARITY:
            raise ValueError(
                f"Error when processing the granularity {property_name} is not supported. Only {', '.join(READ_GROUP_NUMBER_GRANULARITY.keys())} are supported"
            )
        granularity = READ_GROUP_NUMBER_GRANULARITY[property_name]
        # Embed granularity as a SQL literal for GROUP BY consistency (see above).
        return SQL("date_part('%s', %%s)" % granularity, sql_expr)

    @override
    def convert_to_column(
        self,
        value,
        record: BaseModel,
        values: dict | None = None,
        validate: bool = True,
    ) -> typing.Any:
        return self.convert_to_cache(value, record, validate=validate)


class Date(BaseDate[date]):
    """Encapsulates a python :class:`date <datetime.date>` object."""

    type = "date"
    _column_type = ("date", "date")

    if not typing.TYPE_CHECKING:
        # Runtime fast path; the type checker inherits BaseDate[date].__get__.
        __get__ = _make_scalar_get(lambda v: False if v is None else v)

    @staticmethod
    def today(*args) -> date:
        """Return the current day in the format expected by the ORM.

        .. note:: This function may be used to compute default values.
        """
        return date.today()

    @staticmethod
    def context_today(
        record: BaseModel, timestamp: date | datetime | None = None
    ) -> date:
        """Return the current date as seen in the client's timezone in a format
        fit for date fields.

        .. note:: This method may be used to compute default values.

        :param record: recordset from which the timezone will be obtained.
        :param timestamp: optional datetime value to use instead of
            the current date and time (must be a datetime, regular dates
            can't be converted between timezones).
        """
        today = timestamp or datetime.now()
        tz = record.env.tz
        today_utc = today.replace(tzinfo=utc)  # UTC = no DST
        today = today_utc.astimezone(tz)
        return today.date()

    @staticmethod
    def to_date(
        value: str | date | datetime | typing.Literal[False] | None,
    ) -> date | None:
        """Attempt to convert ``value`` to a :class:`date` object.

        .. warning::

            If a datetime object is given as value,
            it will be converted to a date object and all
            datetime-specific information will be lost (HMS, TZ, ...).

        :param value: value to convert.
        :type value: str or date or datetime
        :return: an object representing ``value``.
        """
        if not value:
            return None
        if isinstance(value, date):
            if isinstance(value, datetime):
                return value.date()
            return value
        value = value[:DATE_LENGTH]
        # fromisoformat (C-level) is ~44x faster than strptime for ISO dates, but
        # it rejects non-zero-padded components (e.g. "2020-9-30") that the legacy
        # strptime parser accepted. Keep the fast path and fall back to strptime
        # for those so imports/onchange remain backwards compatible.
        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.strptime(value, DATE_FORMAT).date()

    from_string = to_date  # deprecated alias, kept for backwards compatibility

    @staticmethod
    def to_string(
        value: date | typing.Literal[False],
    ) -> str | typing.Literal[False]:
        """Convert a :class:`date` or :class:`datetime` object to a string.

        Returns ``value`` in the server's date format; a :class:`datetime` is
        truncated (hours, minutes, seconds, tzinfo dropped).
        """
        return value.strftime(DATE_FORMAT) if value else False

    @override
    def convert_to_cache(
        self, value, record: BaseModel, validate: bool = True
    ) -> typing.Any:
        if not value:
            return None
        # to_date() truncates a datetime to a date, so data files that pass a
        # datetime to a Date field (e.g. CRM demo data) are handled there.
        return self.to_date(value)

    @override
    def convert_to_export(self, value: typing.Any, record: BaseModel) -> typing.Any:
        return self.to_date(value) or ""

    @override
    def convert_to_display_name(
        self, value: typing.Any, record: BaseModel
    ) -> str | typing.Literal[False]:
        return Date.to_string(value)


class Datetime(BaseDate[datetime]):
    """Encapsulates a python :class:`datetime <datetime.datetime>` object."""

    type = "datetime"
    _column_type = ("timestamp", "timestamp")

    if not typing.TYPE_CHECKING:
        # Runtime fast path; the type checker inherits BaseDate[datetime].__get__.
        __get__ = _make_scalar_get(lambda v: False if v is None else v)

    @staticmethod
    def now(*args) -> datetime:
        """Return the current day and time in the format expected by the ORM.

        .. note:: This function may be used to compute default values.
        """
        # drop microseconds: they don't comply with the server datetime format
        return datetime.now().replace(microsecond=0)

    @staticmethod
    def today(*args) -> datetime:
        """Return the current day, at midnight (00:00:00)."""
        return Datetime.now().replace(hour=0, minute=0, second=0)

    @staticmethod
    def context_timestamp(record: BaseModel, timestamp: datetime) -> datetime:
        """Return the given timestamp converted to the client's timezone.

        .. note:: This method is *not* meant for use as a default initializer,
            because datetime fields are automatically converted upon
            display on client side. For default values, :meth:`now`
            should be used instead.

        :param record: recordset from which the timezone will be obtained.
        :param datetime timestamp: naive datetime value (expressed in UTC)
            to be converted to the client timezone.
        :return: timestamp converted to timezone-aware datetime in context timezone.
        :rtype: datetime
        """
        assert isinstance(timestamp, datetime), "Datetime instance expected"
        tz = record.env.tz
        utc_timestamp = timestamp.replace(tzinfo=utc)  # UTC = no DST
        return utc_timestamp.astimezone(tz)

    @staticmethod
    def to_datetime(
        value: str | date | datetime | typing.Literal[False] | None,
    ) -> datetime | None:
        """Convert an ORM ``value`` into a :class:`datetime` value.

        Accepts timezone-aware UTC datetimes and converts them to naive UTC.

        :param value: value to convert.
        :type value: str or date or datetime
        :return: an object representing ``value`` as a naive UTC datetime.
        """
        if not value:
            return None
        if isinstance(value, date):
            if isinstance(value, datetime):
                if value.tzinfo:
                    # aware datetimes: normalize to naive UTC
                    if value.tzinfo is UTC or value.tzinfo == UTC:
                        return value.replace(tzinfo=None)
                    return value.astimezone(UTC).replace(tzinfo=None)
                return value
            return datetime.combine(value, time.min)

        # fromisoformat (C-level) is ~61x faster than strptime for ISO datetimes,
        # but it rejects non-zero-padded components (e.g. "2020-9-30 5:00:00")
        # that the legacy strptime parser accepted. Keep the fast path and fall
        # back to strptime for those so imports remain backwards compatible.
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            value = datetime.strptime(value[:DATETIME_LENGTH], DATETIME_FORMAT)
        # ISO strings with offsets (e.g. Luxon's toISO() from the JS client)
        # yield aware datetimes: normalize to naive UTC like the datetime path.
        if value.tzinfo:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    from_string = to_datetime  # deprecated alias, kept for backwards compatibility

    @staticmethod
    def to_string(
        value: datetime | typing.Literal[False],
    ) -> str | typing.Literal[False]:
        """Convert a :class:`datetime` or :class:`date` object to a string.

        :param value: value to convert.
        :type value: datetime or date
        :return: a string representing ``value`` in the server's datetime format,
            if ``value`` is of type :class:`date`,
            the time portion will be midnight (00:00:00).
        """
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
                # only use the timezone from the context; the cached value is a
                # naive UTC datetime, so anchor it to UTC before converting --
                # a bare ``astimezone`` on a naive value assumes server-local
                # time and is wrong on non-UTC servers (matches the SQL path's
                # ``timezone('UTC', ...)`` and ``context_timestamp``).
                dt = dt.replace(tzinfo=utc).astimezone(get_timezone(tz_name))
            return get_property(dt)

        return getter

    @override
    def convert_to_cache(
        self, value, record: BaseModel, validate: bool = True
    ) -> typing.Any:
        return self.to_datetime(value)

    @override
    def convert_to_export(self, value: typing.Any, record: BaseModel) -> typing.Any:
        value = self.convert_to_display_name(value, record)
        return self.to_datetime(value) or ""

    @override
    def convert_to_display_name(
        self, value: typing.Any, record: BaseModel
    ) -> str | typing.Literal[False]:
        if not value:
            return False
        return Datetime.to_string(Datetime.context_timestamp(record, value))
