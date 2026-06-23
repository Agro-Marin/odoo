"""DDL detection and client-side parameter inlining.

psycopg 3 binds parameters server-side by default, but PostgreSQL's extended
query protocol only accepts ``$N`` parameters in *value* positions (WHERE,
INSERT VALUES, …); DDL structural positions (column types, ``DEFAULT``
expressions, ``COMMENT`` bodies, sequence options) reject them outright.
Upstream psycopg 2 always substituted client-side, so this subsystem is the
debt the psycopg 2→3 migration introduced: detect DDL cheaply, then splice the
parameters in as quoted literals.

Kept in its own module — rather than inline in :mod:`odoo.db.cursor` — so the
security-sensitive client-side splicing lives in a small, independently
testable unit.  All names here are pure functions/constants with no cursor or
connection state.
"""

import re as _re
from typing import Any

from psycopg import sql as _sql

# DDL keywords that need client-side parameter inlining: PostgreSQL's extended
# query protocol rejects $N parameters in DDL structural positions (column
# types, constraints, comments, sequence options).
#
# Excluded (Odoo never parameterizes them): TRUNCATE, SET, VACUUM, ANALYZE,
# REINDEX, CLUSTER, LOCK.  To add one, edit only this tuple — the regex
# (``_RE_DDL``) and the prefix gate (``_DDL_PREFIXES``) are both derived from it
# at import, so they cannot drift (exercised by ``TestDDLKeywordPrefixGate``).
_DDL_KEYWORDS: tuple[str, ...] = (
    "CREATE",
    "ALTER",
    "DROP",
    "COMMENT",
    "GRANT",
    "REVOKE",
    "DO",
)
# Comment introducers that may precede a DDL keyword (``-- ...`` / ``/* ... */``).
# The regex skips them, so the prefix gate must admit them too.
_COMMENT_PREFIXES: frozenset[str] = frozenset(("--", "/*"))

# Match the DDL keyword even when preceded by SQL comments: without the
# comment-skip, ``-- migrate\nCREATE TABLE ...`` slips past detection and a
# later ``SELECT *`` raises "cached plan must not change result type".
_RE_DDL = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*"
    r"(" + "|".join(_DDL_KEYWORDS) + r")\b",  # group(1) = the matched keyword
    _re.IGNORECASE | _re.DOTALL,
)
# First two chars for fast prefix filtering — skips the regex on the 99% of
# queries that are SELECT/INSERT/UPDATE/DELETE (which share no 2-char prefix
# with any DDL keyword).  Derived from ``_DDL_KEYWORDS`` so it can't drift.
_DDL_PREFIXES: frozenset[str] = (
    frozenset(kw[:2] for kw in _DDL_KEYWORDS) | _COMMENT_PREFIXES
)

# DDL that changes a relation's shape or existence.  Only these invalidate the
# prepared-statement cache and the process-global schema_cache.  COMMENT/GRANT/
# REVOKE need param inlining but don't change shape, so they skip it; ``DO`` may
# run arbitrary DDL, so it's treated as schema-changing.  Tested against the
# UPPERCASE keyword from :func:`_ddl_keyword`.
_SCHEMA_CHANGING_DDL: frozenset[str] = frozenset({"CREATE", "ALTER", "DROP", "DO"})


def _ddl_keyword(qs: str) -> str | None:
    """Return the leading DDL keyword (UPPERCASE), or ``None`` if *qs* is not DDL.

    Reporting the keyword (not just yes/no) lets :meth:`Cursor.execute`
    distinguish DDL needing param inlining (every keyword) from DDL that must
    also invalidate the caches (only :data:`_SCHEMA_CHANGING_DDL`).

    The 2-char prefix check gates the costlier regex, skipping it on the 99% of
    SELECT/INSERT/UPDATE/DELETE queries.  The check reads a 64-char lstripped
    window to avoid copying a 100KB+ query; deep indentation (>=63 leading
    spaces) falls back to a full lstrip so it can't slip past the gate.
    """
    head = qs[:64].lstrip()
    if len(head) < 2 and len(qs) > 64:
        head = qs.lstrip()
    c = head[:2].upper()
    if c not in _DDL_PREFIXES:
        return None
    m = _RE_DDL.match(qs)
    return m.group(1).upper() if m is not None else None


def _find_value_markers(query: str) -> list[int]:
    """Return positions of real ``%s`` placeholders in *query*.

    Skips ``%%`` escape sequences, so a literal like ``LIKE 'a%%s'`` is not
    mistaken for a placeholder (naive ``str.count``/``str.replace`` both
    match the ``%s`` inside ``%%s`` and mangle the query).
    """
    out = []
    i, n = 0, len(query)
    while i < n - 1:
        if query[i] == "%":
            if query[i + 1] == "s":
                out.append(i)
            # skip the full token: '%%' escape, '%s' marker, or '%x' junk
            i += 2
        else:
            i += 1
    return out


# Named-parameter markers for the dict path: ``%(name)s`` to substitute or
# ``%%`` as an escaped percent.  A bare ``%`` (e.g. ``-- 50% off``) matches
# neither and is left untouched, instead of crashing ``qs % {...}``.
_DICT_MARKER_RE = _re.compile(r"%(?:%|\(([^)]+)\)s)")


def _inline_ddl_params(qs: str, params: tuple | list | dict, ctx: Any) -> str:
    """Return *qs* with *params* spliced in as client-side quoted literals.

    DDL structural positions (column types, ``DEFAULT`` expressions,
    ``COMMENT`` bodies, sequence options, …) reject server-side ``$N``
    parameters, so the values must be quoted client-side via
    :func:`psycopg.sql.quote` and inlined into the statement text.

    :param qs: the DDL statement text with ``%s`` / ``%(name)s`` markers.
    :param params: positional (tuple/list) or named (dict) parameters.
    :param ctx: a psycopg adapter context (connection/cursor) for ``quote``.
    :return: the statement with every marker replaced by a quoted literal.
    :raises ValueError: if the positional marker count differs from *params*.
    """
    if isinstance(params, dict):
        # %(name)s style.  Substitute via a %%-aware regex (not ``qs % {...}``)
        # so a literal % in the DDL body (e.g. ``IS 'imported -- 50% off'``) is
        # preserved; re.sub with a callable repl inserts values verbatim, so % or
        # \ in them are safe.
        # Validate referenced names up-front: a missing key would otherwise raise
        # a context-less ``KeyError`` from inside re.sub.  Extra keys are left
        # lenient (both psycopg and ``qs % params`` ignore them).
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
            if name is None:  # matched the '%%' escape
                return "%"
            return _sql.quote(params[name], ctx)

        return _DICT_MARKER_RE.sub(_sub_named, qs)
    # Splice quoted values at the real %s markers (not ``qs % (...)``, which
    # misreads a literal % in the DDL body as a format spec).  _find_value_markers
    # is %%-aware; literal %% is unescaped to % in the surrounding segments.
    markers = _find_value_markers(qs)
    if len(markers) != len(params):
        raise ValueError(
            f"DDL parameter count mismatch: {len(markers)} '%s' "
            f"marker(s) but {len(params)} param(s)"
        )
    out, prev = [], 0
    # lengths already validated equal above; strict=True is belt-and-braces
    for pos, value in zip(markers, params, strict=True):
        out.append(qs[prev:pos].replace("%%", "%"))
        out.append(_sql.quote(value, ctx))
        prev = pos + 2
    out.append(qs[prev:].replace("%%", "%"))
    return "".join(out)
