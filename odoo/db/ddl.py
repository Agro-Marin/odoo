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
# never parameterizes them.  If a future caller does, add the keyword to
# ``_DDL_KEYWORDS`` below — the detection regex (``_RE_DDL``) AND the 2-char
# prefix gate (``_DDL_PREFIXES``) are BOTH *computed* from it at import, so
# they cannot drift out of sync as long as the derivations below stay intact.
# (Were they ever to drift, detection would silently fail: a query whose
# keyword the regex matches but whose prefix the gate misses is treated as
# non-DDL — params are not inlined and the auto-prepared statement cache is not
# invalidated.  The derivation is exercised by ``TestDDLKeywordPrefixGate`` in
# test_db_cursor.py, which checks every keyword's prefix is admitted by the
# gate and that no sample query is classified differently by gate vs regex.)
_DDL_KEYWORDS: tuple[str, ...] = (
    "CREATE",
    "ALTER",
    "DROP",
    "COMMENT",
    "GRANT",
    "REVOKE",
    "DO",
)
# Comment introducers that may precede a DDL keyword: a line ``-- ...`` or a
# block ``/* ... */``.  The regex skips them, so the prefix gate must admit
# them too — the second half of the prefix set's single source of truth.
_COMMENT_PREFIXES: frozenset[str] = frozenset(("--", "/*"))

# Match the DDL keyword even when preceded by SQL comments (line ``-- ...``
# or block ``/* ... */``).  Without the comment-skip prefix a statement like
# ``-- migrate\nCREATE TABLE ...`` slips past detection: the auto-prepared
# statement cache is never invalidated and a later ``SELECT *`` raises
# ``cached plan must not change result type`` (verified reproducible).
_RE_DDL = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*"
    r"(" + "|".join(_DDL_KEYWORDS) + r")\b",  # group(1) = the matched keyword
    _re.IGNORECASE | _re.DOTALL,
)
# First two chars of the statement for fast prefix filtering — avoids the regex
# on the 99% of queries that are SELECT/INSERT/UPDATE/DELETE.  Derived from
# ``_DDL_KEYWORDS`` (+ the comment introducers) so it can never drift from the
# regex above; comment-prefixed non-DDL is rare, so the extra regex runs are
# negligible.  SELECT/INSERT/UPDATE/DELETE share no 2-char prefix with any DDL
# keyword, so the gate stays selective.
_DDL_PREFIXES: frozenset[str] = (
    frozenset(kw[:2] for kw in _DDL_KEYWORDS) | _COMMENT_PREFIXES
)

# DDL that changes a relation's shape or existence.  Only these invalidate
# psycopg's auto-prepared-statement cache (a cached ``SELECT *`` plan whose
# result type changed → "cached plan must not change result type") and the
# process-global schema_cache (cached column types / id sequences for binary
# ``copy_from``).  COMMENT / GRANT / REVOKE are DDL for *parameter inlining*
# (they reject server-side ``$N`` params) but never change shape, so they skip
# both invalidations.  ``DO`` can execute arbitrary DDL in its body, so it is
# treated conservatively as schema-changing.  Membership is tested against the
# UPPERCASE keyword returned by :func:`_ddl_keyword`.
_SCHEMA_CHANGING_DDL: frozenset[str] = frozenset({"CREATE", "ALTER", "DROP", "DO"})


def _ddl_keyword(qs: str) -> str | None:
    """Return the leading DDL keyword (UPPERCASE), or ``None`` if *qs* is not DDL.

    Reporting the keyword identity — not just a yes/no — lets
    :meth:`Cursor.execute` distinguish DDL that needs client-side parameter
    inlining (every keyword) from DDL that must additionally invalidate the
    prepared-statement and schema caches (only :data:`_SCHEMA_CHANGING_DDL`).

    The prefix check (a 2-char compare against a frozenset) avoids the regex on
    the 99% of queries that are SELECT/INSERT/UPDATE/DELETE.

    Read the first two non-whitespace chars to gate the (costlier) regex.
    Slice-then-lstrip on a 64-char window keeps the hot path off a full-query
    copy (Odoo's triple-quoted SQL nearly always has leading whitespace, and a
    giant IN-list/VALUES query can be 100KB+).  The window exposes the keyword's
    first 2 chars only while leading whitespace is <=62; at >=63 it yields <2
    keyword chars, so fall back to a full lstrip in that rare case — otherwise
    deeply-indented DDL slips past the gate and its params are never inlined ("no
    parameter $1") and the auto-prepared cache is never invalidated ("cached plan
    must not change result type" on a later SELECT).

    Pure: depends only on *qs* and the module-level ``_DDL_PREFIXES`` / ``_RE_DDL``
    derived from ``_DDL_KEYWORDS``.  Verified equivalent to a bare ``_RE_DDL``
    match across the full indentation range by ``TestDDLDetectionLeadingWhitespace``
    and a 200k-case fuzz; kept as a gate purely for the hot-path speedup.
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
        # Validate referenced names up-front.  A marker whose key is absent
        # would otherwise raise a bare ``KeyError`` from inside ``re.sub`` (no
        # statement context, no marker name in the message); surface it as the
        # same clear ``ValueError`` the positional path raises on a count
        # mismatch.  Extra/unused keys are intentionally left lenient — both
        # psycopg's native ``%(name)s`` binding and the legacy ``qs % params``
        # formatting ignore them, so rejecting them would be a behaviour change.
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
