"""Connection-string normalization and connect-phase error classification.

Split out of :mod:`odoo.db.pool` so this security-sensitive, **pure** logic (no
pool/socket/thread state) is independently testable. Two concerns:

* **DSN normalization** (:func:`_expand_conninfo`, :func:`_normalize_dsn_key`):
  flatten a URI/conninfo string or dict into discrete keywords, folded into a
  hashable pool key whose password is an opaque fingerprint. Every DSN consumer
  routes through :func:`_expand_conninfo`, so the password can never leak into a
  dict key or log.

* **Connect-error classification** (:data:`_NON_RETRYABLE_CONNECT_ERRORS`,
  :func:`_translate_connect_error`): decide whether a connect *attempt* failed
  permanently (missing database, bad auth), so the pool's probe can surface the
  precise psycopg class in ms instead of a ~30s retry.

The network-touching probe stays in :mod:`odoo.db.pool`, which re-imports these
names (so ``from odoo.db.pool import _normalize_dsn_key`` keeps working).
"""

from __future__ import annotations

import hashlib

import psycopg
from psycopg.conninfo import conninfo_to_dict

# Permanent connection failures: retrying can't help (the database, role, or
# password is wrong, not transient capacity).  The pre-flight probe raises these
# immediately instead of letting psycopg_pool retry into a ~30s ``PoolTimeout``.
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

    A connect failure crosses libpq before a SQLSTATE is parsed, so the precise
    subclass is never raised; the server's English FATAL text is the only
    discriminator. Matching fails SAFE: an unrecognised or localised message
    returns ``None`` (left to the pool's retry), so a transient connection
    refused/timeout is never mistaken for permanent. Returning the precise class
    lets ``exp_db_exist`` keep matching ``InvalidCatalogName``.

    This is only the *fast*, English path; a non-English ``lc_messages`` returns
    ``None`` here and the gap is closed by :meth:`ConnectionPool._database_absent`
    (catalog lookup, any locale).
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

    A bare conninfo/URI string is parsed in full.  A dict with an embedded
    ``dsn`` string has it expanded and merged *under* the dict's own keywords
    (which win, per psycopg precedence).  A plain keyword dict is shallow-copied.
    The password is preserved verbatim; callers strip or fingerprint it.

    Single source of truth for the embedded-``dsn`` expansion every DSN consumer
    needs — skipping it is what leaks a URI's password into pool keys and logs.
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

    Aliases ``dbname`` → ``database`` and folds the password into an opaque
    fingerprint, so rotating it invalidates the cached pool without the cleartext
    ever living in a dict key or log.  Embedded-``dsn`` expansion (so a URI and
    the equivalent keywords route to one pool) is via :func:`_expand_conninfo`.
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
