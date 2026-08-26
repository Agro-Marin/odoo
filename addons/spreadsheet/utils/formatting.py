import re
from datetime import datetime, timedelta

from odoo.libs.datetime import timezone

strftime_to_spreadsheet_time_format_table = {
    "%H": "hh",
    "%I": "hh",
    "%M": "mm",
    "%S": "ss",
}

strftime_to_spreadsheet_dateformat_table = {
    "%Y": "yyyy",
    "%y": "yy",
    "%m": "mm",
    "%b": "mmm",
    "%B": "mmmm",
    "%d": "dd",
    "%a": "ddd",
    "%A": "dddd",
}


def strftime_format_to_spreadsheet_time_format(strf_format):
    """Join the recognized time tokens with the source separator, appending " a" for a 12-hour format."""

    twelve_hour_system = False
    parts = []
    for part in re.finditer(r"(%.)", strf_format):
        symbol = part.group(1)
        spreadsheet_symbol = strftime_to_spreadsheet_time_format_table.get(symbol)
        if spreadsheet_symbol:
            parts.append(spreadsheet_symbol)
        if symbol in {"%I", "%p"}:
            twelve_hour_system = True

    separator = re.search(r"(:| )", strf_format)
    separator = separator.group(1) if separator else ":"

    return separator.join(parts) + (" a" if twelve_hour_system else "")


def strftime_format_to_spreadsheet_date_format(strf_format):
    """Join the recognized date tokens with the separator found in the source format."""
    parts = []
    for part in re.finditer(r"(%.)", strf_format):
        symbol = part.group(1)
        spreadsheet_symbol = strftime_to_spreadsheet_dateformat_table.get(symbol)
        if spreadsheet_symbol:
            parts.append(spreadsheet_symbol)

    separator = re.search(r"(/|-| )", strf_format)
    separator = separator.group(1) if separator else "/"

    return separator.join(parts)


INITIAL_1900_DAY = datetime(1899, 12, 30)
SECONDS_PER_DAY = 24 * 60 * 60


def datetime_to_spreadsheet_date_number(dt, tz_name):
    context_tz = timezone(tz_name)
    localized_datetime = dt.astimezone(context_tz)
    offset = localized_datetime.utcoffset() / timedelta(seconds=1)
    timestamp = dt.timestamp() + offset

    delta = timestamp - INITIAL_1900_DAY.timestamp()
    return delta / SECONDS_PER_DAY


def date_to_spreadsheet_date_number(d):
    dt = datetime.combine(d, datetime.min.time())
    delta = dt.timestamp() - INITIAL_1900_DAY.timestamp()
    return delta / SECONDS_PER_DAY
