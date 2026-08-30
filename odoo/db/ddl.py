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
    """(leading keyword needing client-side params, is this a ROLLBACK TO).

    `Cursor.execute` asks both questions of every statement it runs, and each
    answer used to do its own `lstrip`, its own two-character prefix test and
    its own frozenset lookup. Microbenchmarked over 200k iterations on a
    typical ORM SELECT: `_ddl_keyword` 120 ns and `_is_rollback_to_savepoint`
    113 ns, against 47 ns for `_changes_schema` — so the duplicated prefix
    dance was most of the classification cost, and it was the same dance
    twice. One pass takes the three from 280.0 ns to 201.8 ns. All of it
    is invisible through a live round trip (~14 us), which is why
    it has to be measured here rather than end to end.

    Only a comment-led statement can need both regexes: `_DDL_KEYWORDS` and
    `ROLLBACK` share no two-character prefix (`RE`VOKE against `RO`LLBACK), so
    an ordinary statement still runs at most one.

    **`SET` is answered without a regex, and that shape is the whole reason it
    is answered at all.** PostgreSQL rejects `$N` in a `SET` value as it does
    in every DDL position — `SET LOCAL statement_timeout = %s` reaches the
    server only to come back `syntax error at or near "$1"` — and unlike
    `TRUNCATE TABLE %s` or `LOCK TABLE %s`, whose `%s` stands for an
    *identifier* that inlining would quote into a literal and still fail, a
    `SET` value is a value: inlined, `SET statement_timeout = '5s'` runs.
    Verified against PG 18 for both directions.

    Putting `SET` in `_DDL_KEYWORDS` is what costs: it shares `SE` with
    `SELECT`, so every SELECT in the tree would enter `_RE_DDL`, measured
    152.5 ns -> 370.7 ns, and a dedicated `SE`-only regex still costs 301 ns
    because the leading-comment group has to be tried. `SELECT` and `SET`
    part at the *third character*, and nothing else in SQL begins `SE` in
    statement position, so one slice settles it. Reading the head here rather
    than through a helper pays for that slice and more — measured against the
    version this replaces: SELECT +5.4 ns, UPDATE -11.5, INSERT -15.9,
    CREATE -12.4, `ROLLBACK TO` -19.5.

    A comment can never lead a `SET` seen by this branch: `--` and `/*` are in
    `_DDL_PREFIXES`, so a commented statement has already taken the branch
    above and been matched by `_RE_DDL` against the real keyword list.
    """
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
    """Does this statement, or one hidden after a `;`, change the schema?

    The split is textual and has no lexer, so a `;` inside a *literal* followed
    by a DDL word over-reports: `INSERT INTO t (body) VALUES ('step 1; create
    the invoice')` reads as a hidden CREATE. That direction is deliberate,
    since under-reporting leaves a sibling connection holding a stale plan and
    raising `FeatureNotSupported` -- but the cost of a false positive is larger
    than "a cache drop" and is written down here so the trade is priced
    correctly. Measured on a live cursor:

        plain INSERT       prepared 1->1  _schema_changed=False  drains 0
        the INSERT above   prepared 1->0  _schema_changed=True   drains 1

    That is this connection's whole auto-prepared cache discarded mid
    transaction *and* every idle pooled connection for the database closed at
    commit. What keeps it unreachable is that psycopg binds server-side, so a
    value never enters `qs`: instrumented over a fresh `base` install, 18329
    calls, 1003 true DDL by leading keyword, exactly one non-DDL statement
    containing a `;` at all, and zero false positives. Only SQL built with
    inlined literals can trip it.
    """
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
