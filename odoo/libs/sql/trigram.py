"""Trigram search-pattern helpers for PostgreSQL ``pg_trgm`` indexes.

Pure string transforms (no cursor, no ``odoo`` framework imports); relocated
from ``odoo/tools/sql.py`` under ADR-0004.
"""

import re

from odoo.libs.json import dumps as json_dumps

_WILDCARD_ESCAPE_RE = re.compile(r"(_|%|\\)")
_TRIGRAM_PATTERN_RE = re.compile(
    r"""
    (
        (?:.)*?           # 0 or more characters including newline
        (?<!\\)(?:\\\\)*  # 0 or even number of backslashes
    )
    (?:_|%|$)             # a non-escaped wildcard character or end of string
    """,
    re.VERBOSE | re.DOTALL,
)
_PG_UNESCAPE_RE = re.compile(r"\\(.|$)", re.DOTALL)


def value_to_translated_trigram_pattern(value: str) -> str:
    """Escape value to match a translated field's trigram index content.

    The trigram index function jsonb_path_query_array("column_name", '$.*')::text
    uses all translations' representations to build the indexed text. So the
    original text needs to be JSON-escaped correctly to match it.

    :param str value: value provided in domain
    :return: a pattern to match the indexed text
    """
    if len(value) < 3:
        return "%"

    json_escaped = json_dumps(value, ensure_ascii=False)[1:-1]

    wildcard_escaped = _WILDCARD_ESCAPE_RE.sub(r"\\\1", json_escaped)

    return f"%{wildcard_escaped}%"


def pattern_to_translated_trigram_pattern(pattern: str) -> str:
    """Escape pattern to match a translated field's trigram index content.

    The trigram index function jsonb_path_query_array("column_name", '$.*')::text
    uses all translations' representations to build the indexed text. So the
    original pattern needs to be JSON-escaped correctly to match it.

    :param str pattern: value provided in domain
    :return: a pattern to match the indexed text
    """
    sub_patterns = _TRIGRAM_PATTERN_RE.findall(pattern)

    sub_texts = [_PG_UNESCAPE_RE.sub(r"\1", t) for t in sub_patterns]

    json_escaped = [
        json_dumps(t, ensure_ascii=False)[1:-1] for t in sub_texts if len(t) >= 3
    ]

    wildcard_escaped = [_WILDCARD_ESCAPE_RE.sub(r"\\\1", t) for t in json_escaped]

    return f"%{'%'.join(wildcard_escaped)}%" if wildcard_escaped else "%"
