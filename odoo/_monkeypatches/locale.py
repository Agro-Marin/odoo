import datetime
import locale
import time


def patch_module() -> None:
    """Give Windows the `nl_langinfo` pieces POSIX provides natively.

    `locale.nl_langinfo` and its `D_FMT`/`T_FMT` constants are POSIX-only, and
    Odoo reads the platform's date and time formats through them. On Windows
    they are absent, so each is supplied here.

    The replacement recovers the format string by formatting a known instant
    and substituting the pieces back out -- 30/12/2004 and 13:24:56 are chosen
    so no component can be mistaken for another. Every branch is guarded by
    `hasattr`, so this whole patch is inert on POSIX.
    """
    if not hasattr(locale, "D_FMT"):
        locale.D_FMT = 1

    if not hasattr(locale, "T_FMT"):
        locale.T_FMT = 2

    if not hasattr(locale, "nl_langinfo"):

        def nl_langinfo(param: int) -> str | None:
            if param == locale.D_FMT:
                val = time.strptime("30/12/2004", "%d/%m/%Y")
                dt = datetime.datetime(*val[:6])
                format_date = dt.strftime("%x")
                for x, y in [
                    ("30", "%d"),
                    ("12", "%m"),
                    ("2004", "%Y"),
                    ("04", "%Y"),
                ]:
                    format_date = format_date.replace(x, y)
                return format_date
            if param == locale.T_FMT:
                val = time.strptime("13:24:56", "%H:%M:%S")
                dt = datetime.datetime(*val[:6])
                format_time = dt.strftime("%X")
                for x, y in [("13", "%H"), ("24", "%M"), ("56", "%S")]:
                    format_time = format_time.replace(x, y)
                return format_time
            return None

        locale.nl_langinfo = nl_langinfo
