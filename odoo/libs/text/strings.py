__all__ = [
    "get_flag",
    "human_size",
    "is_encodable",
    "mod10r",
    "remove_accents",
    "str2bool",
]

import unicodedata
import warnings
from typing import Literal


def remove_accents(input_str: str) -> str:
    if not input_str:
        return input_str
    nkfd_form = unicodedata.normalize("NFKD", input_str)
    return "".join(c for c in nkfd_form if not unicodedata.combining(c))


def is_encodable(value: str, charset: str = "ascii") -> bool:
    """Can ``value`` survive ``charset`` once its accents are folded away?

    Lived on ``mail.alias`` as ``_is_encodable`` although nothing about it is an
    alias -- its only callers are in ``account.journal``, deciding whether a company
    or journal name can go into an email address at all. ``LookupError`` is caught
    with the encoding errors on purpose: an unknown charset is a caller's bug, but
    this is a predicate, and a predicate that raises is not one.
    """
    if not value:
        return False
    try:
        remove_accents(value).encode(charset)
    except LookupError, UnicodeEncodeError:
        return False
    return True


def human_size(sz: float | str) -> str | Literal[False]:
    if not sz:
        return False
    units = ("bytes", "Kb", "Mb", "Gb", "Tb", "Pb", "Eb")
    if isinstance(sz, str):
        sz = len(sz)
    s, i = float(sz), 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024
        i += 1
    return f"{s:0.2f} {units[i]}"


def str2bool(s: str | bool, default: bool | None = None) -> bool:
    if type(s) is bool:
        return s

    if not isinstance(s, str):
        warnings.warn(
            f"Passed a non-str to `str2bool`: {s}",
            DeprecationWarning,
            stacklevel=2,
        )
        if default is None:
            msg = "Use 0/1/yes/no/true/false/on/off"
            raise ValueError(msg)
        return bool(default)

    s = s.lower()
    if s in ("y", "yes", "1", "true", "t", "on"):
        return True
    if s in ("n", "no", "0", "false", "f", "off"):
        return False
    if default is None:
        msg = "Use 0/1/yes/no/true/false/on/off"
        raise ValueError(msg)
    return bool(default)


def mod10r(number: str) -> str:
    codec = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
    report = 0
    result = ""
    for digit in number:
        result += digit
        if digit.isdigit():
            report = codec[(int(digit) + report) % 10]
    return result + str((10 - report) % 10)


_REGIONAL_INDICATOR_A = 0x1F1E6


def get_flag(country_code: str) -> str:
    code = country_code.upper()
    if len(code) != 2 or not ("A" <= code[0] <= "Z" and "A" <= code[1] <= "Z"):
        msg = f"country_code must be two ASCII letters, got {country_code!r}"
        raise ValueError(msg)
    return "".join(chr(_REGIONAL_INDICATOR_A + ord(c) - ord("A")) for c in code)
