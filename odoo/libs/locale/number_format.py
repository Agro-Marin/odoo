from __future__ import annotations

import ast
import functools
import re
from collections.abc import Sequence
from typing import Any, Protocol


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
    # Every group is `*`-quantified, so this pattern matches any string,
    # the empty one included.
    assert matched is not None, f"intersperse_pat failed on {string!r}"
    left, rest, right = matched.groups()

    def reverse(s: str) -> str:
        return s[::-1]

    splits = split(reverse(rest), counts)
    res = separator.join(reverse(s) for s in reversed(splits))
    return left + res + right, (len(splits) > 0 and len(splits) - 1) or 0


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

    decimal_point = lang_data.decimal_point
    if grouping:
        lang_grouping, thousands_sep = (
            lang_data.grouping,
            lang_data.thousands_sep or "",
        )
        eval_lang_grouping = parse_grouping(lang_grouping)

        if spec[-1] in "eEfFgG":
            parts = formatted.split(".")
            if "e" not in formatted and "E" not in formatted:
                parts[0] = intersperse(parts[0], eval_lang_grouping, thousands_sep)[0]

            formatted = decimal_point.join(parts)

        elif spec[-1] in "diu":
            formatted = intersperse(formatted, eval_lang_grouping, thousands_sep)[0]

    elif spec[-1] in "eEfFgG" and "." in formatted:
        formatted = formatted.replace(".", decimal_point)

    return formatted
