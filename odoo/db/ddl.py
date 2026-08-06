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


def _ddl_keyword(qs: str) -> str | None:
    """Return the leading DDL keyword (UPPERCASE), or ``None`` if *qs* is not DDL.

    Reporting the keyword (not just yes/no) lets :meth:`Cursor.execute`
    distinguish DDL needing param inlining (every keyword) from DDL that must
    also invalidate the caches (only :data:`_SCHEMA_CHANGING_DDL`).

    The 2-char prefix check gates the costlier regex, skipping it on the 99% of
    SELECT/INSERT/UPDATE/DELETE queries.  The check reads a 64-char lstripped
    window to avoid copying a 100KB+ query; deep indentation (>=63 leading
    spaces) falls back to a full lstrip so it can't slip past the gate.

    .. note::
        Only the LEADING statement is inspected, which is what parameter
        inlining needs (psycopg cannot bind server-side params into a
        multi-statement string at all — it raises "cannot insert multiple
        commands into a prepared statement" — so such a statement only ever
        runs with ``params=None``).  Cache invalidation must look further:
        see :func:`_changes_schema`.
    """
    head = qs[:64].lstrip()
    if len(head) < 2 and len(qs) > 64:
        head = qs.lstrip()
    c = head[:2].upper()
    if c not in _DDL_PREFIXES:
        return None
    m = _RE_DDL.match(qs)
    return m.group(1).upper() if m is not None else None


_RE_ROLLBACK_TO_SAVEPOINT = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*" r"ROLLBACK\s+TO\b",
    _re.IGNORECASE | _re.DOTALL,
)


def _is_rollback_to_savepoint(qs: str) -> bool:
    """True when *qs*'s leading statement is a ``ROLLBACK TO [SAVEPOINT] name``.

    A partial rollback undoes DDL executed since the savepoint, so a cursor that
    memoised post-DDL catalog facts must drop them — the same reason
    :class:`~odoo.db.savepoint.Savepoint` fires ``_on_rollback_to_savepoint``.
    Code that opens savepoints through :meth:`Cursor.savepoint` gets that hook
    for free; code that issues the raw SQL (some addons still do) bypassed it,
    leaving ``schema_cache`` describing a schema that no longer exists — the
    exact stale-OID hazard binary ``COPY`` then encodes against. Detecting it
    here re-arms the hook for both paths.

    The ``SAVEPOINT`` keyword is optional in PostgreSQL (``ROLLBACK TO name``
    works), so it is not required. A bare ``ROLLBACK`` (no ``TO``) ends the
    whole transaction and is handled elsewhere; ``RELEASE SAVEPOINT`` merges
    without undoing state, so neither needs this.

    Gated on the ``RO`` 2-char prefix like :func:`_ddl_keyword`, so ordinary
    SELECT/INSERT/UPDATE/DELETE queries never reach the regex.
    """
    head = qs[:32].lstrip()
    if len(head) < 2 and len(qs) > 32:
        head = qs.lstrip()
    # ``RO`` for ROLLBACK, plus the comment prefixes the regex skips over (a
    # ``ROLLBACK`` may sit behind a leading ``--``/``/*`` comment).
    if head[:2].upper() not in ("RO", *_COMMENT_PREFIXES):
        return False
    return _RE_ROLLBACK_TO_SAVEPOINT.match(qs) is not None


def _changes_schema(qs: str, leading: str | None) -> bool:
    """True when ANY statement in *qs* changes a relation's shape.

    :meth:`Cursor.execute` uses this — not ``leading in _SCHEMA_CHANGING_DDL`` —
    to decide whether to drop the prepared-statement and catalog caches, because
    a multi-statement string can hide its DDL behind a harmless first statement.
    ``"BEGIN; ALTER TABLE t ADD COLUMN c int; COMMIT"`` leads with ``BEGIN``, so
    a leading-keyword test misses it and the next ``SELECT *`` on a cached plan
    raises ``FeatureNotSupported`` ("cached plan must not change result type") —
    sqlstate 0A000, which is not retryable, so the RPC loop turns it into a 500.

    Cost: the ``";"`` test is a single scan, ~27ns on a typical ORM query
    against a ~18µs round-trip, and only queries that actually contain a
    semicolon pay for the split.

    Splitting on every ``";"`` is deliberately naive.  It cannot MISS a real
    statement boundary (every boundary is a semicolon, so every following
    statement becomes a fragment whose start is examined); it can only
    over-report, when a semicolon inside a string literal or a dollar-quoted
    body happens to be followed by a DDL keyword.  Over-reporting costs one
    unnecessary cache drop and is safe, so the trade is right way round — a
    real SQL tokenizer here would buy nothing but risk.

    :param qs: the statement text.
    :param leading: the result of :func:`_ddl_keyword` for *qs*, reused so the
        common single-statement path costs nothing extra.
    """
    if leading in _SCHEMA_CHANGING_DDL:
        return True
    if ";" not in qs:
        return False
    return any(_ddl_keyword(part) in _SCHEMA_CHANGING_DDL for part in qs.split(";")[1:])


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
            i += 2
        else:
            i += 1
    return out


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
    markers = _find_value_markers(qs)
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
