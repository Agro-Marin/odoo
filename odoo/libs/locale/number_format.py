"""Locale-aware number formatting. Pure Python, no Odoo dependencies.

This is the registry-free half of ``res.lang``'s formatting. It lived in
``odoo/addons/base/models/res_lang.py`` — an *addon* — while
``odoo/tools/formatting.py`` (framework core) reached into that addon twice with
deferred imports to call :func:`format_number`. The dependency pointed the wrong
way: the core cannot require an addon to be importable to format a number.

Nothing here touches a cursor, a registry or a recordset. :func:`format_number`
was already documented in its previous home as the *"pure, registry-free,
DB-free"* counterpart of ``ResLang.format``, which is a description of something
that belongs in ``libs/``.

The locale data arrives through the :class:`LocaleConventions` protocol rather
than the concrete ``LangData``, so this module stays free of the model layer
while ``LangData`` — a ``ReadonlyDict`` exposing exactly these three keys as
attributes — satisfies it structurally, without importing anything from here.
Same technique as ``odoo/orm/components/_protocols.py`` (ADR-0002).

The implementations are moved **verbatim**, including
:func:`split`'s ``0``/``-1`` conventions and the ``lru_cache`` on
:func:`parse_grouping` (which exists because ``grouping`` comes from a small
Selection and this sits on the QWeb number/currency rendering hot path).
"""

from __future__ import annotations

import ast
import functools
import re
from typing import Any, Protocol


class LocaleConventions(Protocol):
    """The locale data a number format needs: the three separator conventions.

    ``odoo.addons.base.models.res_lang.LangData`` satisfies this structurally.
    """

    @property
    def decimal_point(self) -> str:
        """Radix separator, e.g. ``"."`` or ``","``."""
        ...

    @property
    def grouping(self) -> str:
        """Digit-group sizes as a Python-literal list, e.g. ``"[3,0]"``."""
        ...

    @property
    def thousands_sep(self) -> str:
        """Group separator, e.g. ``","``."""
        ...


@functools.lru_cache(maxsize=128)
def parse_grouping(grouping: str) -> tuple[int, ...]:
    """Parse a locale grouping spec (e.g. ``"[3,0]"``) to a tuple, cached.

    RL-P1: input is one of a tiny bounded set (the ``grouping`` Selection), so
    caching avoids an ``ast.literal_eval`` per value on the QWeb number/currency
    rendering hot path.
    """
    return tuple(ast.literal_eval(grouping))


def split(l: str, counts: list[int]) -> list[str]:
    """Chop ``l`` left-to-right into chunks of the given ``counts``.

    A count of ``0`` repeats the previous size until the string is consumed; a
    count of ``-1`` stops splitting and keeps the rest as a single chunk.

    >>> split("hello world", [])
    ['hello world']
    >>> split("hello world", [1])
    ['h', 'ello world']
    >>> split("hello world", [2])
    ['he', 'llo world']
    >>> split("hello world", [2, 3])
    ['he', 'llo', ' world']
    >>> split("hello world", [2, 3, 0])
    ['he', 'llo', ' wo', 'rld']
    >>> split("hello world", [2, -1, 3])
    ['he', 'llo world']

    """
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


def intersperse(string: str, counts: list[int], separator: str = "") -> tuple[str, int]:
    """Group the number in ``string`` from the right and join the groups with ``separator``.

    Used to apply thousands separators. The leading non-space run (after any
    non-digit prefix) is split into groups and rejoined; ``counts`` gives the
    group sizes, interpreted by :func:`split` on the reversed run. The prefix
    and everything from the first space on are left untouched.

    :return: the grouped string and the number of separators inserted
    :rtype: tuple[str, int]
    """
    left, rest, right = intersperse_pat.match(string).groups()

    def reverse(s: str) -> str:
        return s[::-1]

    splits = split(reverse(rest), counts)
    res = separator.join(reverse(s) for s in reverse(splits))
    return left + res + right, (len(splits) > 0 and len(splits) - 1) or 0


def format_number(
    spec: str,
    value: Any,
    lang_data: LocaleConventions,
    grouping: bool = False,
) -> str:
    """Format ``value`` per ``spec`` and ``lang_data``'s locale conventions.

    Pure, registry-free counterpart of ``ResLang.format``: all locale data
    (``decimal_point``, ``grouping``, ``thousands_sep``) comes from
    ``lang_data``, so this is DB-free and callable by code already holding the
    conventions. Handles float (``%e``/``%f``/``%g``) and integer
    (``%d``/``%i``/``%u``) specs; scientific-notation output is never grouped.
    """
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
