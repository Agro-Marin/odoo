"""Date, time, and number formatting utilities for Odoo."""

import datetime
import re
import typing

import babel.dates

from odoo.libs.datetime import utc
from odoo.libs.datetime.tz import timezone as get_timezone
from odoo.libs.locale import posix_to_ldml
from odoo.libs.numbers.float_utils import float_round

from .locale_utils import babel_locale_parse, get_lang

if typing.TYPE_CHECKING:
    from odoo.api import Environment

NON_BREAKING_SPACE = "\N{NO-BREAK SPACE}"

DEFAULT_SERVER_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_SERVER_TIME_FORMAT = "%H:%M:%S"
DEFAULT_SERVER_DATETIME_FORMAT = (
    f"{DEFAULT_SERVER_DATE_FORMAT} {DEFAULT_SERVER_TIME_FORMAT}"
)

DATE_LENGTH = len(datetime.date.today().strftime(DEFAULT_SERVER_DATE_FORMAT))

# strftime only supports the directives available on the platform's libc;
# map to the C89-standard directives, which are available everywhere, for
# cross-platform behavior.
DATETIME_FORMATS_MAP = {
    "%C": "",  # century
    "%D": "%m/%d/%Y",  # modified %y->%Y
    "%e": "%d",
    "%E": "",  # special modifier
    "%F": "%Y-%m-%d",
    "%g": "%Y",  # modified %y->%Y
    "%G": "%Y",
    "%h": "%b",
    "%k": "%H",
    "%l": "%I",
    "%n": "\n",
    "%O": "",  # special modifier
    "%P": "%p",
    "%R": "%H:%M",
    "%r": "%I:%M:%S %p",
    "%s": "",  # num of seconds since epoch
    "%T": "%H:%M:%S",
    "%t": " ",  # tab
    "%u": " %w",
    "%V": "%W",
    "%y": "%Y",  # Even if %y works, it's ambiguous, so we should use %Y
    "%+": "%Y-%m-%d %H:%M:%S",
    # %Z is a special case that causes 2 problems at least:
    #  - the timezone names we use (in res_user.context_tz) come
    #    from IANA/zoneinfo, but not all these names are recognized by
    #    strptime(), so we cannot convert in both directions
    #    when such a timezone is selected and %Z is in the format
    #  - %Z is replaced by an empty string in strftime() when
    #    there is not tzinfo in a datetime value (e.g when the user
    #    did not pick a context_tz). The resulting string does not
    #    parse back if the format requires %Z.
    # As a consequence, we strip it completely from format strings.
    # The user can always have a look at the context_tz in
    # preferences to check the timezone.
    "%z": "",
    "%Z": "",
}


def formatLang(
    env: Environment,
    value: float | typing.Literal[""],
    digits: int = 2,
    grouping: bool = True,
    dp: str | None = None,
    currency_obj: typing.Any | None = None,
    rounding_method: typing.Literal[
        "HALF-UP", "HALF-DOWN", "HALF-EVEN", "UP", "DOWN"
    ] = "HALF-EVEN",
    rounding_unit: typing.Literal[
        "decimals", "units", "thousands", "lakhs", "millions"
    ] = "decimals",
) -> str:
    """Format ``value`` to the appropriate number format of the language in use.

    :param env: The environment.
    :param value: The value to format.
    :param digits: The number of decimal digits.
    :param grouping: Whether to use language grouping.
    :param dp: Name of the decimal precision to use; overrides ``digits`` and
        ``currency_obj`` precision.
    :param currency_obj: Currency to use; overrides ``digits`` precision.
    :param rounding_method: The rounding method:
        **'HALF-UP'**/**'HALF-DOWN'**/**'HALF-EVEN'** round to the closest number,
        ties going away from zero / towards zero / to the closest even number;
        **'UP'**/**'DOWN'** always round away from / towards zero.
    :param rounding_unit: The unit to round to: **decimals** (``digits``/``dp``
        precision), or **units**/**thousands**/**lakhs**/**millions** (no decimals).

    :returns: The formatted value.
    """
    # Empty string is a valid "no value" input; pass it through unformatted.
    if value == "":
        return ""

    if rounding_unit == "decimals":
        if dp:
            digits = env["decimal.precision"].precision_get(dp)
        elif currency_obj:
            digits = currency_obj.decimal_places
    else:
        digits = 0

    rounding_unit_mapping = {
        "decimals": 1,
        "thousands": 10**3,
        "lakhs": 10**5,
        "millions": 10**6,
        "units": 1,
    }

    value /= rounding_unit_mapping[rounding_unit]

    rounded_value = float_round(
        value, precision_digits=digits, rounding_method=rounding_method
    )
    # Deferred import: odoo.tools must stay importable before the addons
    # (locale_utils type-checks the same import).
    from odoo.addons.base.models.res_lang import format_number

    # get_lang() already returns the full LangData; hand it straight to the
    # pure formatter instead of round-tripping through browse().format(),
    # which would re-fetch the same LangData (two extra cache hops per
    # formatted number on the QWeb monetary hot path).
    formatted_value = format_number(
        f"%.{digits}f", rounded_value, get_lang(env), grouping=grouping
    )

    if currency_obj and currency_obj.symbol:
        arguments = (formatted_value, NON_BREAKING_SPACE, currency_obj.symbol)

        return "%s%s%s" % (
            arguments if currency_obj.position == "after" else arguments[::-1]
        )

    return formatted_value


def format_date(
    env: Environment,
    value: datetime.datetime | datetime.date | str,
    lang_code: str | None = None,
    date_format: str | typing.Literal[False] = False,
) -> str:
    """Format a date in a given format.

    :param env: an environment.
    :param value: the date to format (date, datetime or string).
    :param lang_code: the lang code; if omitted, taken from the environment context.
    :param date_format: the LDML format; if omitted, the lang's default format.
    :return: the date formatted in the specified format.
    :rtype: str
    """
    if not value:
        return ""
    from odoo.fields import Datetime

    if isinstance(value, str):
        if len(value) < DATE_LENGTH:
            return ""
        if len(value) > DATE_LENGTH:
            # a datetime, convert to correct timezone
            value = Datetime.from_string(value)
            value = Datetime.context_timestamp(env["res.lang"], value)
        else:
            value = Datetime.from_string(value)
    elif isinstance(value, datetime.datetime) and not value.tzinfo:
        # a datetime, convert to correct timezone
        value = Datetime.context_timestamp(env["res.lang"], value)

    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    if not date_format:
        date_format = posix_to_ldml(lang.date_format, locale=locale)

    assert isinstance(value, datetime.date)  # datetime is a subclass of date
    return babel.dates.format_date(value, format=date_format, locale=locale)


def parse_date(
    env: Environment, value: str, lang_code: str | None = None
) -> datetime.date | str:
    """Parse a localized date string, returning the original string if invalid.

    :param env: an environment.
    :param value: the date to parse.
    :param lang_code: the lang code; if omitted, taken from the environment context.
    :return: date object from the localized string
    :rtype: datetime.date
    """
    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    try:
        return babel.dates.parse_date(value, locale=locale)
    except Exception:
        return value


def format_datetime(
    env: Environment,
    value: datetime.datetime | str,
    tz: str | typing.Literal[False] = False,
    dt_format: str = "medium",
    lang_code: str | None = None,
) -> str:
    """Format the datetime in a given format.

    :param env:
    :param str|datetime value: naive datetime to format either in string or in datetime
    :param str tz: name of the timezone in which the given datetime should be localized
    :param str dt_format: one of "full", "long", "medium", or "short", or a custom date/time pattern compatible with `babel` lib
    :param str lang_code: ISO code of the language to use to render the given datetime
    :rtype: str
    """
    if not value:
        return ""
    if isinstance(value, str):
        from odoo.fields import Datetime

        timestamp = Datetime.from_string(value)
    else:
        timestamp = value

    tz_name = tz or env.user.tz or "UTC"
    utc_datetime = timestamp.replace(tzinfo=utc)
    try:
        context_tz = get_timezone(tz_name)
        localized_datetime = utc_datetime.astimezone(context_tz)
    except Exception:
        localized_datetime = utc_datetime

    lang = get_lang(env, lang_code)

    locale = babel_locale_parse(
        lang.code or lang_code
    )  # lang can be inactive, so `lang`is empty
    if not dt_format or dt_format == "medium":
        date_format = posix_to_ldml(lang.date_format, locale=locale)
        time_format = posix_to_ldml(lang.time_format, locale=locale)
        dt_format = f"{date_format} {time_format}"

    # Babel formats a datetime in a given language without changing locale
    # (month 1 = January in English, janvier in French). Default is 'medium',
    # not 'short':
    #     medium:  Jan 5, 2016, 10:20:31 PM |   5 janv. 2016 22:20:31
    #     short:   1/5/16, 10:20 PM         |   5/01/16 22:20
    # Formats reference: http://babel.pocoo.org/en/latest/dates.html#date-fields
    return babel.dates.format_datetime(localized_datetime, dt_format, locale=locale)


def format_time(
    env: Environment,
    value: datetime.time | datetime.datetime | str,
    tz: str | typing.Literal[False] = False,
    time_format: str = "medium",
    lang_code: str | None = None,
) -> str:
    """Format the given time (hour, minute, second) per the user's preferences (language, format, ...).

    :param env:
    :param value: the time to format; a naive ``datetime.time`` is used as-is (may
        be timezoned to display tzinfo in formats that show it, e.g. 'full'), a
        ``datetime.datetime`` or string is localized to ``tz`` first
    :param tz: name of the timezone in which the given datetime should be localized
    :param time_format: one of "full", "long", "medium", or "short", or a custom time pattern
    :param lang_code: ISO language code
    :rtype: str
    """
    if not value:
        return ""

    if isinstance(value, datetime.time):
        localized_time = value
    else:
        if isinstance(value, str):
            from odoo.fields import Datetime

            value = Datetime.from_string(value)
        assert isinstance(value, datetime.datetime)
        tz_name = tz or env.user.tz or "UTC"
        utc_datetime = value.replace(tzinfo=utc)
        try:
            context_tz = get_timezone(tz_name)
            localized_dt = utc_datetime.astimezone(context_tz)
            # Freeze the UTC offset as a fixed timezone so that timetz()
            # produces a deterministic offset independent of today's DST state.
            # ZoneInfo on a bare time uses today's date to resolve DST, which
            # gives wrong offsets when the original date and today differ in
            # DST status (e.g. formatting a January time in March).
            fixed_offset = datetime.timezone(localized_dt.utcoffset())
            localized_time = localized_dt.replace(tzinfo=fixed_offset).timetz()
        except Exception:
            localized_time = utc_datetime.timetz()

    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    if not time_format or time_format == "medium":
        time_format = posix_to_ldml(lang.time_format, locale=locale)

    return babel.dates.format_time(localized_time, format=time_format, locale=locale)


def _format_time_ago(
    env: Environment,
    time_delta: datetime.timedelta,
    lang_code: str | None = None,
    add_direction: bool = True,
) -> str:
    if not lang_code:
        langs: list[str] = [code for code, _ in env["res.lang"].get_installed()]
        if (ctx_lang := env.context.get("lang")) in langs:
            lang_code = ctx_lang
        else:
            lang_code = env.user.company_id.partner_id.lang or langs[0]
        assert isinstance(lang_code, str)
    locale = babel_locale_parse(lang_code)
    return babel.dates.format_timedelta(
        -time_delta, add_direction=add_direction, locale=locale
    )


def format_decimalized_number(number: float, decimal: int = 1) -> str:
    """Format a number with the nearest metric unit appended.

    Omit decimals when all visible digits are zero. Cap at "Tera"; most people
    don't know what a "Yotta" is.

    ::

        >>> format_decimalized_number(123_456.789)
        123.5k
        >>> format_decimalized_number(123_000.789)
        123k
        >>> format_decimalized_number(-123_456.789)
        -123.5k
        >>> format_decimalized_number(0.789)
        0.8
    """
    for unit in ["", "k", "M", "G"]:
        if abs(number) < 1000.0:
            return f"{round(number, decimal):g}{unit}"
        number /= 1000.0
    return f"{round(number, decimal):g}T"


def format_decimalized_amount(amount: float, currency: typing.Any = None) -> str:
    """Format an amount with its currency symbol and metric unit.

    ::

        >>> format_decimalized_amount(123_456.789, env.ref("base.USD"))
        $123.5k
    """
    formated_amount = format_decimalized_number(amount)

    if not currency:
        return formated_amount

    if currency.position == "before":
        return f"{currency.symbol or ''}{formated_amount}"

    return f"{formated_amount} {currency.symbol or ''}"


def format_amount(
    env: Environment,
    amount: float,
    currency: typing.Any,
    lang_code: str | None = None,
    trailing_zeroes: bool = True,
) -> str:
    fmt = f"%.{currency.decimal_places}f"
    lang = env["res.lang"].browse(get_lang(env, lang_code).id)

    formatted_amount = (
        lang.format(fmt, currency.round(amount), grouping=True)
        .replace(r" ", "\N{NO-BREAK SPACE}")
        .replace(r"-", "-\N{ZERO WIDTH NO-BREAK SPACE}")
    )

    if not trailing_zeroes and currency.decimal_places:
        # Strip trailing zeroes from the *fractional* part only: anchor on the
        # decimal point so integer-part zeroes (e.g. "1,200" for a 0-decimal
        # currency, which never reaches here) are never removed.
        decimal_point = re.escape(lang.decimal_point)
        formatted_amount = re.sub(
            rf"({decimal_point}\d*?)0+$", r"\1", formatted_amount
        )
        formatted_amount = re.sub(rf"{decimal_point}$", "", formatted_amount)

    pre = post = ""
    if currency.position == "before":
        pre = f"{currency.symbol or ''}\N{NO-BREAK SPACE}"
    else:
        post = f"\N{NO-BREAK SPACE}{currency.symbol or ''}"

    return f"{pre}{formatted_amount}{post}"


def format_duration(value: float) -> str:
    """Format a float as a human-readable time span (e.g. 1.5 as "01:30")."""
    hours, minutes = divmod(abs(value) * 60, 60)
    minutes = round(minutes)
    if minutes == 60:
        minutes = 0
        hours += 1
    if value < 0:
        return "-%02d:%02d" % (hours, minutes)
    return "%02d:%02d" % (hours, minutes)
