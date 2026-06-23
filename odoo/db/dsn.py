"""Connection-string normalization and connect-phase error classification.

Split out of :mod:`odoo.db.pool` — like :mod:`odoo.db.ddl` / :mod:`odoo.db.errors`
— so the security-sensitive, **pure** logic that turns a caller's connection
info into a pool routing key (and that classifies a connection *attempt's*
failure) lives in a small, independently testable unit with no pool, socket, or
thread state.

Two concerns live here, and only these:

* **DSN normalization** (:func:`_expand_conninfo`, :func:`_normalize_dsn_key`):
  flattening a URI/conninfo string or dict into discrete keywords, and folding
  that into a hashable pool key whose password is reduced to an opaque
  fingerprint.  This is the single place that must never leak a cleartext
  password into a dict key or log artifact, so keeping it isolated — rather than
  re-derived per call site — removes the risk of one copy drifting from the
  others.  Every DSN consumer (the pool key, :meth:`Connection.dsn`, the
  maintenance-DB probe) routes through :func:`_expand_conninfo`.

* **Connect-error classification** (:data:`_NON_RETRYABLE_CONNECT_ERRORS`,
  :func:`_translate_connect_error`): deciding whether a connection *attempt*
  failed for a permanent reason (missing database, bad auth) that retrying can
  never fix.  The pool's pre-flight probe uses this to surface the precise
  psycopg class in milliseconds instead of letting psycopg_pool retry for ~30s.

The pool's network-touching probe orchestration (``_probe_connectable`` /
``_database_absent``) stays in :mod:`odoo.db.pool`: it does I/O and reads as pool
behaviour.  It imports these pure helpers from here.

:mod:`odoo.db.pool` re-imports every public-to-it name below, so existing
references such as ``from odoo.db.pool import _normalize_dsn_key`` keep working.
"""

from __future__ import annotations

import hashlib

import psycopg
from psycopg.conninfo import conninfo_to_dict

# Connection failures whose cause is permanent: retrying cannot help, because
# the database, role, or password is the problem — not transient capacity.
# psycopg_pool's background worker does not know this; left alone it retries
# the failed connection until ``borrow``'s ~30s getconn budget expires, then
# surfaces an opaque ``PoolTimeout``.  The pre-flight probe in
# ``ConnectionPool._get_or_create_pool`` raises these immediately instead, which
# is what makes ``exp_db_exist``'s ``except InvalidCatalogName`` fast path
# reachable again.
# NB: InvalidPassword (28P01) is NOT a subclass of
# InvalidAuthorizationSpecification (28000) in psycopg 3 — list both.
_NON_RETRYABLE_CONNECT_ERRORS: tuple[type[psycopg.Error], ...] = (
    psycopg.errors.InvalidCatalogName,  # 3D000 — database does not exist
    psycopg.errors.InvalidAuthorizationSpecification,  # 28000 — role / pg_hba rejection
    psycopg.errors.InvalidPassword,  # 28P01 — wrong password
)


def _translate_connect_error(exc: psycopg.OperationalError) -> psycopg.Error | None:
    """Map an untyped connection-phase ``OperationalError`` to its precise,
    permanent psycopg class — or ``None`` when the cause may be transient.

    A connection failure crosses libpq before a SQLSTATE is parsed, so
    ``diag.sqlstate`` is ``None`` and the precise subclass
    (``InvalidCatalogName``, …) is never raised on a *connect*.  The server's
    English FATAL text is the only discriminator left — the same signal
    :class:`odoo.db.pool._SuppressKnownPoolWarnings` already keys on.  Matching
    fails SAFE: an unrecognised or localised message returns ``None`` and is left
    to the pool's retry, so a genuinely transient "connection refused"/timeout
    (which never contains these phrases) is never mistaken for permanent.

    Returning the precise class — rather than a generic error — lets callers
    such as ``exp_db_exist`` keep matching ``InvalidCatalogName`` unchanged.

    .. note::
        This text-match is **locale-dependent** and intentionally only the
        *fast* path: on a server with ``lc_messages`` set to e.g. ``es_MX`` the
        FATAL reads "no existe la base de datos" and this returns ``None``.
        That gap is closed by :meth:`ConnectionPool._database_absent`, which
        confirms a missing database via the ``postgres`` catalog regardless of
        server language.  Pinning the probe's language via
        ``options='-c lc_messages=C'`` was rejected: the database-existence
        check fires *before* startup ``-c`` GUCs are applied (verified — a
        bogus ``-c`` param yields "database does not exist", not "unrecognized
        configuration parameter", against a missing DB).
    """
    msg = str(exc).lower()
    if 'database "' in msg and "does not exist" in msg:
        return psycopg.errors.InvalidCatalogName(str(exc))
    if (
        "password authentication failed" in msg
        or "no pg_hba.conf entry" in msg
        or ('role "' in msg and "does not exist" in msg)
        or "is not permitted to log in" in msg
    ):
        return psycopg.errors.InvalidAuthorizationSpecification(str(exc))
    return None


def _expand_conninfo(info: dict | str) -> dict:
    """Flatten connection info into discrete keyword components.

    A bare conninfo/URI string is parsed in full.  A dict carrying an embedded
    ``dsn`` URI/conninfo string has that string expanded into its components and
    merged *under* the dict's own explicit keywords — which win, matching
    psycopg's own precedence.  A plain keyword dict is returned as a shallow
    copy.  The password is preserved verbatim; callers strip it (safe logging)
    or fold it into a fingerprint (pool key) as their own contract requires.

    Single source of truth for the embedded-``dsn`` expansion that every DSN
    consumer (:func:`_normalize_dsn_key`, :meth:`Connection.dsn`,
    :meth:`ConnectionPool._database_absent`) needs.  Skipping that expansion is
    exactly what leaks a URI's cleartext password into pool keys and DEBUG logs,
    so keeping it in one audited place — rather than re-derived per call site —
    removes the risk of one copy drifting from the others.
    """
    if isinstance(info, str):
        return conninfo_to_dict(info)
    raw = info.get("dsn")
    if raw:
        return {
            **conninfo_to_dict(raw),
            **{k: v for k, v in info.items() if k != "dsn"},
        }
    return dict(info)


def _normalize_dsn_key(dsn: dict | str) -> frozenset:
    """Normalize a DSN to a hashable key for pool lookup.

    Aliases ``dbname`` → ``database``.  Folds the password into an opaque
    fingerprint so rotating the password invalidates the cached pool, but the
    cleartext never lives in memory as a dict key or log artifact.  The embedded
    -``dsn`` expansion (so a URI routes to the same pool as the equivalent
    keywords, and its password is fingerprinted rather than leaked into the key)
    is shared with the other DSN consumers via :func:`_expand_conninfo`.
    """
    dsn = _expand_conninfo(dsn)
    # BLAKE2s-64 is fast, collision-resistant enough for pool routing, and
    # avoids leaking password length information via the key repr.
    password = dsn.get("password")
    if password:
        pw_fp = hashlib.blake2s(str(password).encode(), digest_size=8).hexdigest()
    else:
        pw_fp = ""
    alias_keys = {"dbname": "database"}
    items = (
        (alias_keys.get(k, k), str(v))
        for k, v in dsn.items()
        if k != "password" and v is not None
    )
    return frozenset((*items, ("password_fp", pw_fp)))
