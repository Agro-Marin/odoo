"""Parse a human-typed or machine-extracted decimal amount.

The separators are guessed from the string's own structure, never from a locale, so the
same reading applies to a value an accountant typed and to one captured out of a bank
statement label.
"""

import math
import re

__all__ = ["parse_amount", "split_amount_str"]

_GROUPINGS_RE = re.compile(r"[ '\xa0]")
_SIGN_RE = re.compile(r"\A\s*([+-]?)\s*(.*?)\s*\Z", re.DOTALL)


def _is_solitary_group(int_part: str, distance: int, has_grouping: bool) -> bool:
    return (
        not has_grouping
        and distance == 3
        and int_part.isdigit()
        and len(int_part) <= 3
        and int_part != "0"
    )


def _split(amount_str: str) -> tuple[str, str] | None:
    if not any(char.isdigit() for char in amount_str):
        return None
    has_grouping = bool(_GROUPINGS_RE.search(amount_str))
    amount_str = _GROUPINGS_RE.sub("", amount_str).strip()
    commas = amount_str.count(",")
    dots = amount_str.count(".")
    last_comma, last_dot = amount_str.rfind(","), amount_str.rfind(".")
    comma_distance = len(amount_str) - 1 - last_comma if last_comma >= 0 else -1
    dot_distance = len(amount_str) - 1 - last_dot if last_dot >= 0 else -1

    match (commas, dots):
        case (0, 0):
            tsep, dsep = ",", "."  # '1334'
        case (c, 0) if c > 1:
            tsep, dsep = ",", "."  # '1,334,567'
        case (0, d) if d > 1:
            tsep, dsep = ".", ","  # '1.334.567'
        case (c, 1) if c > 1:
            tsep, dsep = ",", "."
        case (1, d) if d > 1:
            tsep, dsep = ".", ","
        case (1, 1) if last_comma > last_dot:
            tsep, dsep = ".", ","
        case (1, 1):
            tsep, dsep = ",", "."
        case (0, 1) if _is_solitary_group(amount_str[:last_dot], dot_distance, has_grouping):
            tsep, dsep = ".", ","  # best possible assumption
        case (0, 1):
            tsep, dsep = ",", "."
        case (1, 0) if _is_solitary_group(amount_str[:last_comma], comma_distance, has_grouping):
            tsep, dsep = ",", "."  # best possible assumption
        case (1, 0):
            tsep, dsep = ".", ","
        case _:
            return None

    parts = amount_str.replace(tsep, "").split(dsep)
    if len(parts) > 2:
        return None
    int_part, dec_part = (parts + ["0"])[:2]
    int_part = int_part or "0"
    dec_part = dec_part or "0"
    if not int_part.isdigit() or not dec_part.isdigit():
        return None
    return (int_part, dec_part)


def split_amount_str(amount_str: str) -> tuple[str, str]:
    """Split a localized amount string into its integer and decimal parts.

    :param amount_str: the amount string to parse
    :return: tuple of (int_part, dec_part) as strings, ('0', '0') when the string is
             empty or its separators are ambiguous
    """
    if not amount_str:
        return ("0", "0")
    return _split(amount_str) or ("0", "0")


def parse_amount(amount_str: str | None) -> float | None:
    """Read a decimal amount out of a string, tolerating either separator convention.

    Unlike ``float()`` this accepts the groupings and the comma decimal separator most of
    the world writes, and rejects the non-finite literals ``float()`` silently accepts
    (``inf``, ``nan``, and any magnitude that overflows to infinity).

    :param amount_str: the amount string to parse
    :return: the amount, or None when the string is not a finite decimal number
    """
    if not amount_str:
        return None
    sign, body = _SIGN_RE.match(amount_str).groups()  # type: ignore[union-attr]
    parts = _split(body)
    if parts is None:
        return None
    value = float(f"{parts[0]}.{parts[1]}")
    if not math.isfinite(value):
        return None
    return -value if sign == "-" else value
