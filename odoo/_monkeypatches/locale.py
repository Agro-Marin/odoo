import datetime
import locale
import time


def patch_module() -> None:
    # typeshed declares D_FMT/T_FMT Final because on POSIX they are; these two
    # branches exist for the platforms (Windows) where nl_langinfo and its
    # constants are absent altogether, which is exactly what hasattr tests.
    if not hasattr(locale, "D_FMT"):
        locale.D_FMT = 1  # type: ignore[misc]

    if not hasattr(locale, "T_FMT"):
        locale.T_FMT = 2  # type: ignore[misc]

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

        # The stdlib signature returns str; this stand-in returns None for the
        # constants it does not synthesise, which is what the callers here
        # already handle.
        locale.nl_langinfo = nl_langinfo  # type: ignore[assignment]
