from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = [
    "ABSOLUTE",
    "ISO_DATE",
    "ISO_DATETIME",
    "LEAD",
    "PARENS",
    "SIGN_STYLES",
    "TRAIL",
    "from_bool",
    "from_date",
    "from_datetime",
    "from_float",
    "from_value",
    "group_digits",
]

LEAD = "lead"
TRAIL = "trail"
PARENS = "parens"
ABSOLUTE = "absolute"

SIGN_STYLES = (LEAD, TRAIL, PARENS, ABSOLUTE)

ISO_DATE = "%Y-%m-%d"
ISO_DATETIME = "%Y-%m-%d %H:%M:%S"


def group_digits(digits: str, thousand: str = "", every: int = 3) -> str:
    if not thousand or every <= 0 or len(digits) <= every:
        return digits
    head = len(digits) % every or every
    parts = [digits[:head]]
    parts += [digits[i : i + every] for i in range(head, len(digits), every)]
    return thousand.join(parts)


def from_float(
    value: float | str | Decimal,
    *,
    places: int = 2,
    thousand: str = "",
    decimal: str = ".",
    symbol: str = "",
    sign: str = LEAD,
    implied_point: bool = False,
) -> str:
    if sign not in SIGN_STYLES:
        raise ValueError(f"Unknown sign style {sign!r}; expected one of {SIGN_STYLES}")
    if places < 0:
        raise ValueError(f"places must not be negative, got {places}")
    try:
        # str() first: Decimal(0.1) is 0.1000000000000000055511151231257827,
        # and quantizing that rounds a total the document never stated.
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"{value!r} is not a number") from e
    if not number.is_finite():
        raise ValueError(f"{value!r} has no finite value to write")

    # ROUND_HALF_UP, not Python's banker's default: every money format this
    # layer writes for -- an invoice total, a payroll line, a bank file -- is
    # specified half-up, and a layer that silently rounds 2.675 down to 2.67
    # disagrees with the document it is meant to reproduce.
    number = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    negative = number < 0
    digits = f"{abs(number):.{places}f}"
    whole, _, fraction = digits.partition(".")

    if implied_point:
        body = f"{whole}{fraction}"
    else:
        body = group_digits(whole, thousand)
        if fraction:
            body = f"{body}{decimal}{fraction}"
    if symbol:
        body = f"{symbol}{body}"

    if not negative or sign == ABSOLUTE:
        return body
    if sign == PARENS:
        return f"({body})"
    if sign == TRAIL:
        return f"{body}-"
    return f"-{body}"


def from_date(value: datetime.date | str, fmt: str = ISO_DATE) -> str:
    if isinstance(value, str):
        if len(value) != 10:
            msg = f"{value!r} is not a valid date"
            raise ValueError(msg)
        value = datetime.date.fromisoformat(value)
    if isinstance(value, datetime.datetime):
        value = value.date()
    if not isinstance(value, datetime.date):
        raise ValueError(f"{value!r} is not a date")
    return value.strftime(fmt)


def from_datetime(value: datetime.datetime | str, fmt: str = ISO_DATETIME) -> str:
    if isinstance(value, str):
        value = datetime.datetime.fromisoformat(value)
    if not isinstance(value, datetime.datetime):
        raise ValueError(f"{value!r} is not a datetime")
    return value.strftime(fmt)


def from_bool(value: object, true: str = "1", false: str = "0") -> str:
    return true if value else false


def from_value(value: object, **options: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return from_bool(
            value,
            str(options.get("true", "1")),
            str(options.get("false", "0")),
        )
    if isinstance(value, datetime.datetime):
        return from_datetime(value, str(options.get("datetime_format", ISO_DATETIME)))
    if isinstance(value, datetime.date):
        return from_date(value, str(options.get("date_format", ISO_DATE)))
    if isinstance(value, (int, float, Decimal)):
        return from_float(value, **options)  # type: ignore[arg-type]
    return str(value)
