from __future__ import annotations

import collections
import datetime
import re
import unicodedata
from collections.abc import Container, Sequence

__all__ = [
    "infer_separators",
    "normalize_number",
    "strip_currency_symbol",
    "to_date",
    "to_datetime",
    "to_float",
]
_FLOAT_RE = re.compile(r"([+-]?[0-9.,]+)")

_DECORATIONS = "()-+"


def infer_separators(
    value: str, thousand: str = " ", decimal: str = "."
) -> tuple[str, str]:
    non_number = [
        character
        for character in value
        if character not in _DECORATIONS
        if unicodedata.category(character) not in ("Nd", "Sc")
    ]
    counts = collections.Counter(non_number)
    if len(counts) == 2 and counts[non_number[-1]] == 1:
        grouping, point = (character for character, _count in counts.most_common())
        return grouping, point
    return thousand, decimal


def strip_currency_symbol(
    value: str, symbols: Container[str] | None = None
) -> str | None:
    value = value.strip()
    negative = False
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
        negative = True

    parts = [part for part in _FLOAT_RE.split(value) if part]
    if len(parts) > 2:
        return None
    if len(parts) == 1:
        if _FLOAT_RE.search(parts[0]) is None:
            return None
        return f"-{parts[0]}" if negative else parts[0]

    symbol_index = 1 if _FLOAT_RE.search(parts[0]) is not None else 0
    symbol = parts[symbol_index].strip()
    if symbols is None:
        known = bool(symbol) and all(
            unicodedata.category(character) == "Sc" for character in symbol
        )
    else:
        known = symbol in symbols
    if not known:
        return None
    number = parts[(symbol_index + 1) % 2]
    return f"-{number}" if negative else number


def normalize_number(
    value: str,
    *,
    symbols: Container[str] | None = None,
    thousand: str = " ",
    decimal: str = ".",
) -> str | None:
    grouping, point = infer_separators(value, thousand, decimal)
    if "e" in value or "E" in value:
        try:
            value = f"{float(value.replace(grouping, '.')):f}"
            grouping = " "
        except ValueError:
            pass
    value = value.replace(grouping, "").replace(point, ".")
    return strip_currency_symbol(value, symbols)


def to_float(
    value: str | float,
    *,
    symbols: Container[str] | None = None,
    thousand: str = " ",
    decimal: str = ".",
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{value!r} is a boolean, not a number")
    if isinstance(value, (int, float)):
        return float(value)
    normalized = normalize_number(
        value, symbols=symbols, thousand=thousand, decimal=decimal
    )
    if normalized is not None:
        try:
            return float(normalized)
        except ValueError:
            pass
    bare = "".join(
        character for character in value if unicodedata.category(character) != "Sc"
    ).strip()
    normalized = normalize_number(
        bare, symbols=symbols, thousand=thousand, decimal=decimal
    )
    if normalized is None:
        raise ValueError(f"{value!r} does not state a number")
    return float(normalized)


def to_date(value: datetime.date | str, formats: Sequence[str] = ()) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if len(text) == 10:
        return datetime.date.fromisoformat(text)
    try:
        return datetime.datetime.fromisoformat(text).date()
    except ValueError:
        msg = f"{value!r} is not a valid date"
        raise ValueError(msg) from None


def to_datetime(
    value: datetime.datetime | str, formats: Sequence[str] = ()
) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.datetime.fromisoformat(text)
