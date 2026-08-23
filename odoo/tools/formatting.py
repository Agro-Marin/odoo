import datetime
import re
import typing

import babel.dates

from odoo.libs.datetime import timezone as get_timezone
from odoo.libs.datetime import utc
from odoo.libs.locale import format_number, posix_to_ldml
from odoo.libs.numbers import float_round

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

ROUNDING_UNIT_MAPPING = {
    "decimals": 1,
    "thousands": 10**3,
    "lakhs": 10**5,
    "millions": 10**6,
    "units": 1,
}

DATETIME_FORMATS_MAP = {
    "%C": "",
    "%D": "%m/%d/%Y",
    "%e": "%d",
    "%E": "",
    "%F": "%Y-%m-%d",
    "%g": "%Y",
    "%G": "%Y",
    "%h": "%b",
    "%k": "%H",
    "%l": "%I",
    "%n": "\n",
    "%O": "",
    "%P": "%p",
    "%R": "%H:%M",
    "%r": "%I:%M:%S %p",
    "%s": "",
    "%T": "%H:%M:%S",
    "%t": " ",
    "%u": " %w",
    "%V": "%W",
    "%y": "%Y",
    "%+": "%Y-%m-%d %H:%M:%S",
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
    if value == "":
        return ""

    if rounding_unit == "decimals":
        if dp:
            digits = env["decimal.precision"].get_precision(dp)
        elif currency_obj:
            digits = currency_obj.decimal_places
    else:
        digits = 0

    value /= ROUNDING_UNIT_MAPPING[rounding_unit]

    rounded_value = float_round(
        value, precision_digits=digits, rounding_method=rounding_method
    )

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
    if not value:
        return ""
    from odoo.fields import Datetime

    if isinstance(value, str):
        if len(value) < DATE_LENGTH:
            return ""
        if len(value) > DATE_LENGTH:
            value = Datetime.from_string(value)
            value = Datetime.context_timestamp(env["res.lang"], value)
        else:
            value = Datetime.from_string(value)
    elif isinstance(value, datetime.datetime) and not value.tzinfo:
        value = Datetime.context_timestamp(env["res.lang"], value)

    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    if not date_format:
        date_format = posix_to_ldml(lang.date_format, locale=locale)

    if not isinstance(value, datetime.date):
        raise TypeError(f"format_date() expects a date, got {type(value).__name__}")
    return babel.dates.format_date(value, format=date_format, locale=locale)


def parse_date(
    env: Environment, value: str, lang_code: str | None = None
) -> datetime.date | str:
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

    locale = babel_locale_parse(lang.code)
    if not dt_format or dt_format == "medium":
        date_format = posix_to_ldml(lang.date_format, locale=locale)
        time_format = posix_to_ldml(lang.time_format, locale=locale)
        dt_format = f"{date_format} {time_format}"

    return babel.dates.format_datetime(localized_datetime, dt_format, locale=locale)


def format_time(
    env: Environment,
    value: datetime.time | datetime.datetime | str,
    tz: str | typing.Literal[False] = False,
    time_format: str = "medium",
    lang_code: str | None = None,
) -> str:
    if not value:
        return ""

    if isinstance(value, datetime.time):
        localized_time = value
    else:
        if isinstance(value, str):
            from odoo.fields import Datetime

            value = Datetime.from_string(value)
        if not isinstance(value, datetime.datetime):
            raise TypeError(
                f"format_time() expects a datetime, got {type(value).__name__}"
            )
        tz_name = tz or env.user.tz or "UTC"
        utc_datetime = value.replace(tzinfo=utc)
        try:
            context_tz = get_timezone(tz_name)
            localized_dt = utc_datetime.astimezone(context_tz)
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
    # `get_lang` is the one place that resolves a language. This used to walk
    # installed languages itself and got it subtly wrong: no `en_US` preference,
    # no `with_context(lang="en_US")` on the company read, an IndexError with no
    # language installed, and -- the one that showed -- no check that the
    # company's language is installed at all before handing it to babel.
    locale = babel_locale_parse(lang_code or get_lang(env).code)
    return babel.dates.format_timedelta(
        -time_delta, add_direction=add_direction, locale=locale
    )


def format_decimalized_number(number: float, decimal: int = 1) -> str:
    units = ("", "k", "M", "G", "T")
    for unit in units[:-1]:
        rounded = round(number, decimal)
        if abs(rounded) < 1000.0:
            return f"{rounded:g}{unit}"
        number /= 1000.0
    return f"{round(number, decimal):g}{units[-1]}"


def format_decimalized_amount(amount: float, currency: typing.Any = None) -> str:
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
    lang = get_lang(env, lang_code)

    formatted_amount = (
        format_number(fmt, currency.round(amount), lang, grouping=True)
        .replace(" ", "\N{NO-BREAK SPACE}")
        .replace("-", "-\N{ZERO WIDTH NO-BREAK SPACE}")
    )

    if not trailing_zeroes and currency.decimal_places:
        decimal_point = re.escape(lang.decimal_point)
        formatted_amount = re.sub(rf"({decimal_point}\d*?)0+$", r"\1", formatted_amount)
        formatted_amount = re.sub(rf"{decimal_point}$", "", formatted_amount)

    pre = post = ""
    if currency.position == "before":
        pre = f"{currency.symbol or ''}\N{NO-BREAK SPACE}"
    else:
        post = f"\N{NO-BREAK SPACE}{currency.symbol or ''}"

    return f"{pre}{formatted_amount}{post}"


def format_duration(value: float) -> str:
    hours, minutes = divmod(abs(value) * 60, 60)
    minutes = round(minutes)
    if minutes == 60:
        minutes = 0
        hours += 1
    if value < 0:
        return "-%02d:%02d" % (hours, minutes)
    return "%02d:%02d" % (hours, minutes)
