from __future__ import annotations

import hashlib

import psycopg
from psycopg.conninfo import conninfo_to_dict

_NON_RETRYABLE_CONNECT_ERRORS: tuple[type[psycopg.Error], ...] = (
    psycopg.errors.InvalidCatalogName,
    psycopg.errors.InvalidAuthorizationSpecification,
    psycopg.errors.InvalidPassword,
)


def _translate_connect_error(exc: psycopg.OperationalError) -> psycopg.Error | None:
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
    dsn = _expand_conninfo(dsn)
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
