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

# DDL statements that must use client-side parameter formatting.
# PostgreSQL's extended query protocol only accepts $N parameters in
# value positions (WHERE, INSERT VALUES, etc.).  DDL structural
# positions (column types, constraints, comments, sequence options)
# reject parameterized values outright.
#
# Intentionally excluded: TRUNCATE, SET, VACUUM, ANALYZE, REINDEX,
# CLUSTER, LOCK — these also reject server-side parameters, but Odoo
# never parameterizes them.  If a future caller does, extend BOTH the
# regex AND ``_DDL_PREFIXES`` (the 2-char prefix gate below).
# Match the DDL keyword even when preceded by SQL comments (line ``-- ...``
# or block ``/* ... */``).  Without the comment-skip prefix a statement like
# ``-- migrate\nCREATE TABLE ...`` slips past detection: the auto-prepared
# statement cache is never invalidated and a later ``SELECT *`` raises
# ``cached plan must not change result type`` (verified reproducible).
_RE_DDL = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*"
    r"(?:CREATE|ALTER|DROP|COMMENT|GRANT|REVOKE|DO)\b",
    _re.IGNORECASE | _re.DOTALL,
)
# First two chars of the statement for fast prefix filtering — avoids the regex
# on the 99% of queries that are SELECT/INSERT/UPDATE/DELETE.  ``--`` and ``/*``
# are included so comment-prefixed DDL still reaches the regex; comment-prefixed
# non-DDL is rare, so the extra regex runs are negligible.
_DDL_PREFIXES = frozenset(("CR", "AL", "DR", "CO", "GR", "RE", "DO", "--", "/*"))


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


# Named-parameter markers for the dict path: ``%(name)s`` to substitute, or
# ``%%`` as an escaped literal percent.  A bare ``%`` matching neither (e.g.
# ``-- 50% off`` in a COMMENT body) is left untouched, so it is preserved as a
# literal instead of crashing ``qs % {...}`` with a format error.
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
    # psycopg.sql.quote already returns str — no wrapper needed.
    if isinstance(params, dict):
        # %(name)s style.  Substitute named markers with a %%-aware regex
        # rather than ``qs % {...}`` so a literal % in the DDL body — e.g.
        # ``COMMENT ON TABLE t IS 'imported -- 50% off'`` — is preserved
        # instead of raising ``TypeError: not enough arguments for format
        # string``.  This mirrors the escape-aware handling on the positional
        # path below.  re.sub with a callable repl inserts the quoted literal
        # verbatim (no backreference processing), so values containing % or \
        # are safe.
        def _sub_named(m: _re.Match) -> str:
            name = m.group(1)
            if name is None:  # matched the '%%' escape
                return "%"
            return _sql.quote(params[name], ctx)

        return _DICT_MARKER_RE.sub(_sub_named, qs)
    # Splice quoted values at the real %s markers rather than using
    # ``qs % (...)``, which misreads a literal % in the DDL body
    # (e.g. COMMENT ... IS '50% done') as a format spec and raises.
    # _find_value_markers is %%-escape aware; literal %% is then
    # unescaped to % in the surrounding segments to match what the
    # old %-formatting did.
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
