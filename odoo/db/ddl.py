import re as _re
from typing import Any

from psycopg import sql as _sql

from .utils import find_value_markers

_DDL_KEYWORDS: tuple[str, ...] = (
    "CREATE",
    "ALTER",
    "DROP",
    "COMMENT",
    "GRANT",
    "REVOKE",
    "DO",
)
_COMMENT_PREFIXES: frozenset[str] = frozenset(("--", "/*"))

_RE_DDL = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*"
    r"(" + "|".join(_DDL_KEYWORDS) + r")\b",
    _re.IGNORECASE | _re.DOTALL,
)
_DDL_PREFIXES: frozenset[str] = (
    frozenset(kw[:2] for kw in _DDL_KEYWORDS) | _COMMENT_PREFIXES
)

_SCHEMA_CHANGING_DDL: frozenset[str] = frozenset({"CREATE", "ALTER", "DROP", "DO"})


_RE_ROLLBACK_TO_SAVEPOINT = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*" r"ROLLBACK\s+TO\b",
    _re.IGNORECASE | _re.DOTALL,
)
_ROLLBACK_PREFIXES: frozenset[str] = frozenset(("RO",)) | _COMMENT_PREFIXES


def classify_statement(qs: str) -> tuple[str | None, bool]:
    head = qs[:64].lstrip()
    if len(head) < 3 and len(qs) > 64:
        head = qs.lstrip()
    c = head[:2].upper()
    if c in _DDL_PREFIXES:
        m = _RE_DDL.match(qs)
        if m is not None:
            return m.group(1).upper(), False
        if c in _COMMENT_PREFIXES:
            return None, _RE_ROLLBACK_TO_SAVEPOINT.match(qs) is not None
        return None, False
    if c == "SE":
        return ("SET", False) if head[2:3] in ("T", "t") else (None, False)
    if c in _ROLLBACK_PREFIXES:
        return None, _RE_ROLLBACK_TO_SAVEPOINT.match(qs) is not None
    return None, False


def _ddl_keyword(qs: str) -> str | None:
    return classify_statement(qs)[0]


def _changes_schema(qs: str, leading: str | None) -> bool:
    if leading in _SCHEMA_CHANGING_DDL:
        return True
    if ";" not in qs:
        return False
    return any(_ddl_keyword(part) in _SCHEMA_CHANGING_DDL for part in qs.split(";")[1:])


_DICT_MARKER_RE = _re.compile(r"%(?:%|\(([^)]+)\)s)")


def _inline_ddl_params(qs: str, params: tuple | list | dict, ctx: Any) -> str:
    if isinstance(params, dict):
        referenced = {
            m.group(1) for m in _DICT_MARKER_RE.finditer(qs) if m.group(1) is not None
        }
        missing = referenced - params.keys()
        if missing:
            raise ValueError(
                "DDL parameter mismatch: marker(s) "
                + ", ".join(f"%({n})s" for n in sorted(missing))
                + f" have no matching key in params {sorted(params)}"
            )

        def _sub_named(m: _re.Match) -> str:
            name = m.group(1)
            if name is None:
                return "%"
            return _sql.quote(params[name], ctx)

        return _DICT_MARKER_RE.sub(_sub_named, qs)
    markers = find_value_markers(qs)
    if len(markers) != len(params):
        raise ValueError(
            f"DDL parameter count mismatch: {len(markers)} '%s' "
            f"marker(s) but {len(params)} param(s)"
        )
    out, prev = [], 0
    for pos, value in zip(markers, params, strict=True):
        out.append(qs[prev:pos].replace("%%", "%"))
        out.append(_sql.quote(value, ctx))
        prev = pos + 2
    out.append(qs[prev:].replace("%%", "%"))
    return "".join(out)
