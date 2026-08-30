from __future__ import annotations

import ast
import functools
import re
from collections.abc import Sequence
from typing import Any, Protocol

__all__ = [
    "LocaleConventions",
    "format_number",
    "intersperse",
    "parse_grouping",
    "split",
]


class LocaleConventions(Protocol):
    @property
    def decimal_point(self) -> str: ...

    @property
    def grouping(self) -> str: ...

    @property
    def thousands_sep(self) -> str: ...


@functools.lru_cache(maxsize=128)
def parse_grouping(grouping: str) -> tuple[int, ...]:
    return tuple(ast.literal_eval(grouping))


def split(l: str, counts: Sequence[int]) -> list[str]:
    res = []
    saved_count = len(l)
    for count in counts:
        if not l:
            break
        if count == -1:
            break
        if count == 0:
            while l:
                res.append(l[:saved_count])
                l = l[saved_count:]
            break
        res.append(l[:count])
        l = l[count:]
        saved_count = count
    if l:
        res.append(l)
    return res


intersperse_pat = re.compile(r"([^0-9]*)([^ ]*)(.*)")


def intersperse(
    string: str, counts: Sequence[int], separator: str = ""
) -> tuple[str, int]:
    matched = intersperse_pat.match(string)
    assert matched is not None, f"intersperse_pat failed on {string!r}"
    left, rest, right = matched.groups()

    def reverse(s: str) -> str:
        return s[::-1]

    splits = split(reverse(rest), counts)
    res = separator.join(reverse(s) for s in reversed(splits))
    return left + res + right, max(len(splits) - 1, 0)


# `x in "eEfFgG"` is True for the empty string, so these are sets, not a
# substring test: a spec with no conversion at all must match no branch.
_FLOATING = frozenset("eEfFgG")
_INTEGRAL = frozenset("diu")

_CONVERSION_RE = re.compile(
    r"%(?:%|[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?([diouxXeEfFgGcrsab]))"
)


def _conversion_span(spec: str) -> re.Match[str] | None:
    """The first real conversion in the spec, `%%` literals skipped.

    The conversion character was read as `spec[-1]`, which is only itself when
    the spec ends at the conversion. `res_lang.format(percent, value)` is a
    public ORM method taking an arbitrary spec, so `"%.2f%%"` and `"%d units"`
    reach here and were silently left unlocalised. The *span* is returned, not
    just the character, because the literal text around it must be held out of
    the separator rewriting below -- see `format_number`.
    """
    return next(
        (match for match in _CONVERSION_RE.finditer(spec) if match[1] is not None),
        None,
    )


def format_number(
    spec: str,
    value: Any,
    lang_data: LocaleConventions,
    grouping: bool = False,
) -> str:
    if not spec or spec[0] != "%":
        raise ValueError(
            "format_number() must be given exactly one %char format specifier"
        )

    formatted = spec % value
    match = _conversion_span(spec)
    if match is None:
        return formatted
    conversion = match[1]

    # Hold the caller's own literal text out of the rewriting. Searching the
    # whole output for a decimal point took literal periods with it: `"%.2f sec."`
    # on 1234.5 came out `"1.234,50 sec,"`. `% ()` resolves any `%%` in the
    # literal runs, so their lengths match what the format above produced and
    # the number is the slice between them.
    head = spec[: match.start()] % ()
    tail = spec[match.end() :] % ()
    number = formatted[len(head) : len(formatted) - len(tail) or None]

    decimal_point = lang_data.decimal_point
    if grouping:
        lang_grouping, thousands_sep = (
            lang_data.grouping,
            lang_data.thousands_sep or "",
        )
        eval_lang_grouping = parse_grouping(lang_grouping)

        if conversion in _FLOATING:
            parts = number.split(".")
            # An exponent must not be grouped. Which conversions can produce one
            # is known from the spec: e/E always, f/F never, g/G depending on the
            # value. Only that last case has to inspect the output -- scanning it
            # unconditionally, as this did, treats any literal text carrying an
            # "e" as scientific notation, so `"%.2f EUR"` lost its thousands
            # separator to the E in the currency name.
            scientific = conversion in "eE" or (
                conversion in "gG" and ("e" in number or "E" in number)
            )
            if not scientific:
                parts[0] = intersperse(parts[0], eval_lang_grouping, thousands_sep)[0]

            number = decimal_point.join(parts)

        elif conversion in _INTEGRAL:
            number = intersperse(number, eval_lang_grouping, thousands_sep)[0]

    elif conversion in _FLOATING and "." in number:
        number = number.replace(".", decimal_point)

    return head + number + tail
