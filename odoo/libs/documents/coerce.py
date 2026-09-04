from __future__ import annotations

import collections
import datetime
import re
import unicodedata
from collections.abc import Container, Sequence

# Kept out of `strip_currency_symbol`, which runs once per cell of every
# float column: the pattern is a compile-time constant and was being handed to
# `re.compile` (and so to `re`'s internal cache) per value.

__all__ = [
    "infer_separators",
    "normalize_number",
    "strip_currency_symbol",
    "to_date",
    "to_datetime",
    "to_float",
]
_FLOAT_RE = re.compile(r"([+-]?[0-9.,]+)")

# Characters a number may carry that are not part of it: accountants write a
# negative as `(1.00)`, and a currency symbol is Unicode category `Sc`.
_DECORATIONS = "()-+"


def infer_separators(
    value: str, thousand: str = " ", decimal: str = "."
) -> tuple[str, str]:
    """Work out how ``value`` groups and points its digits.

    If there are two different non-numeric characters in the number, the
    duplicated one is the grouping separator and the other -- which must occur
    exactly once -- is the decimal point. Otherwise the caller's defaults
    stand, because one separator alone is ambiguous: ``1.234`` is a thousand
    in Spain and a fraction in the UK, and only the caller knows which.
    """
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
    """``value`` without its currency decoration, or ``None`` if it is not a number.

    ``symbols`` is the set of symbols to accept; ``None`` accepts any run of
    Unicode currency characters, which is what a caller with no currency table
    to consult can honestly check.
    """
    value = value.strip()
    negative = False
    if value.startswith("(") and value.endswith(")"):
        # Accountants write a negative this way.
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
    """``value`` rewritten so ``float()`` accepts it, or ``None`` if it is not one.

    Returns a string rather than a float because the ORM's own loader is what
    turns an import cell into a number, and handing it a float would move that
    decision -- and its error reporting -- somewhere the caller cannot see.
    Use :func:`to_float` when a number is what you want.
    """
    grouping, point = infer_separators(value, thousand, decimal)
    if "e" in value or "E" in value:
        # Scientific notation: the grouping separator is the decimal point
        # here, and expanding it first keeps the replacements below from
        # eating the exponent.
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
    """``value`` as a number, however its document wrote it.

    :raises ValueError: if it does not state one
    """
    if isinstance(value, bool):
        # bool is a subclass of int; a True/False is not a total.
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
    # `1.234,56 €` defeats separator inference, because the space before the
    # symbol counts as a third non-numeric character and the two real
    # separators stop being distinguishable. An importer can leave that to the
    # person looking at the preview; a strategy reading a document cannot, so
    # drop the currency characters and infer again on what is left.
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
    """``value`` as a date.

    ISO-8601 is always accepted; ``formats`` are tried first, in order, for a
    caller that knows how its documents are written. Nothing is guessed: a
    bare ``12/03/2025`` is March in one country and December in another, and a
    framework that picks one silently books an invoice into the wrong period.

    :raises ValueError: if it does not state a date in a shape given
    """
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
    """``value`` as a datetime, on the same terms as :func:`to_date`.

    :raises ValueError: if it does not state one in a shape given
    """
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.datetime.fromisoformat(text)
