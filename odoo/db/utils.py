import os
import re
import warnings
from urllib.parse import parse_qsl, urlsplit

import psycopg
from psycopg.adapt import Loader

from odoo import tools

# Emit the ODOO_PGAPPNAME deprecation at most once per process.  On a
# busy server connection_info_for() fires on every borrow, so the naive
# warn() call produces thousands of duplicates in a single request.
_ODOO_PGAPPNAME_WARNED = False


# Numeric-to-float loader for psycopg3.
# Converts PostgreSQL numeric/decimal to Python float (Odoo convention).
# psycopg3 never calls load() with None (NULLs bypass the loader).
# NB: float loses precision vs Decimal for exact decimal fractions, but
# Odoo's ORM, reports, and JS client all assume float.  Switching to
# Decimal would require changes across the entire stack.
class _NumericToFloatLoader(Loader):
    def load(self, data: bytes) -> float:
        return float(data)


def register_adapters(conn: psycopg.Connection) -> None:
    """Register Odoo's psycopg type adapters on a single connection.

    Scoped per-connection (called from the pool's ``configure`` callback)
    rather than mutating the process-global ``psycopg.adapters`` at import
    time.  A module import must not silently change numeric decoding for every
    psycopg user in the process — a co-resident library, or the obfuscate
    CLI's raw ``VACUUM`` connection, would otherwise inherit float decoding it
    never asked for.  Odoo's query connections all come from the pool, so they
    all get the adapter; nothing else does.

    :param conn: the freshly-created psycopg connection to configure.
    """
    conn.adapters.register_loader("numeric", _NumericToFloatLoader)


# Query categorization patterns — used only for debug-level logging
# statistics, not for correctness.  The optional `"?` handles the
# common case of quoted identifiers but won't match hyphens or closing
# quotes.  The optional schema prefix matches `public.res_users` and
# `"public"."res_users"` — previously these fell through to "other".
# Misclassified queries just produce slightly wrong debug stats, never
# wrong behavior.
re_from = re.compile(
    r'\bfrom\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
re_into = re.compile(
    r'\binto\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)


def categorize_query(decoded_query: str) -> tuple[str, str] | tuple[str, None]:
    """Categorize a SQL query as 'from', 'into', or 'other' and extract the table name.

    :param decoded_query: The SQL query string to categorize
    :return: A tuple of (query_type, table_name) where query_type is 'from', 'into', or 'other'
    """
    res_into = re_into.search(decoded_query)
    # prioritize `insert` over `select` so `select` subqueries are not
    # considered when inside a `insert`
    if res_into:
        return "into", res_into.group(1)

    res_from = re_from.search(decoded_query)
    if res_from:
        return "from", res_from.group(1)

    return "other", None


# TCP health parameters: detect dead connections faster than default
# Linux keepalives (which wait ~2h). psycopg passes these as libpq
# connection keywords. Keywords override DSN values when both are set.
_HEALTH_PARAMS: dict[str, str] = {
    "connect_timeout": "10",  # 10s connection timeout
    "tcp_user_timeout": "30000",  # 30s TCP retransmission timeout
    "keepalives": "1",  # enable TCP keepalives
    "keepalives_idle": "60",  # first probe after 60s idle
    "keepalives_interval": "10",  # 10s between probes
    "keepalives_count": "3",  # give up after 3 failures
    # PG18 wire protocol 3.2: 256-bit cancel keys (vs 32-bit in 3.0).
    # First protocol change since PG 7.4 (2003).
    # Lowered to 3.0 so psycopg accepts the downgrade when PgBouncer
    # (which only speaks 3.0) sits between Odoo and PG18.
    "min_protocol_version": "3.0",
}


def connection_info_for(db_or_uri: str, readonly: bool = False) -> tuple[str, dict]:
    """parse the given `db_or_uri` and return a 2-tuple (dbname, connection_params)

    Connection params are either a dictionary with a single key ``dsn``
    containing a connection URI, or a dictionary containing connection
    parameter keywords which psycopg can build a key/value connection string
    (dsn) from

    :param str db_or_uri: database name or postgres dsn
    :param bool readonly: used to load
        the default configuration from ``db_`` or ``db_replica_``.
    :rtype: (str, dict)
    """
    global _ODOO_PGAPPNAME_WARNED  # noqa: PLW0603 — process-wide once-flag
    app_name = tools.config["db_app_name"]
    if "ODOO_PGAPPNAME" in os.environ:
        if not _ODOO_PGAPPNAME_WARNED:
            warnings.warn(
                "Since 19.0, use PGAPPNAME instead of ODOO_PGAPPNAME",
                DeprecationWarning,
                stacklevel=2,
            )
            _ODOO_PGAPPNAME_WARNED = True
        app_name = os.environ["ODOO_PGAPPNAME"]
    # Using manual string interpolation for security reason and trimming at default NAMEDATALEN=63
    app_name = app_name.replace("{pid}", str(os.getpid()))[:63]

    if db_or_uri.startswith(("postgresql://", "postgres://")):
        # extract db from uri
        us = urlsplit(db_or_uri)
        if len(us.path) > 1:
            db_name = us.path[1:]
        elif us.username:
            db_name = us.username
        else:
            # Last-ditch fallback: libpq defaults dbname to the username when
            # the URI omits a path, so a URI without username or path is
            # malformed.  Using the hostname as the dbname label is almost
            # certainly wrong — warn so the misconfiguration surfaces.
            warnings.warn(
                f"PostgreSQL URI {db_or_uri!r} has no database path and no "
                f"username; using hostname {us.hostname!r} as the database "
                f"name label.  This is likely a misconfiguration.",
                RuntimeWarning,
                stacklevel=2,
            )
            db_name = us.hostname
        # Only inject keys NOT already present in the URI's query string.
        # psycopg applies kwargs over DSN values, so blindly spreading
        # _HEALTH_PARAMS would silently override an operator's explicit
        # ?connect_timeout=60 with our default 10.  Same courtesy for
        # application_name: an explicit ?application_name=... in the URI
        # wins over the db_app_name config default.
        uri_keys = {k for k, _ in parse_qsl(us.query)}
        merged = {k: v for k, v in _HEALTH_PARAMS.items() if k not in uri_keys}
        info = {"dsn": db_or_uri, **merged}
        if "application_name" not in uri_keys:
            info["application_name"] = app_name
        return db_name, info

    connection_info = {"dbname": db_or_uri, "application_name": app_name}
    for p in ("host", "port", "user", "password", "sslmode"):
        cfg = tools.config["db_" + p]
        if readonly:
            # Use replica config only if it's set (not None/empty)
            replica_cfg = tools.config.get("db_replica_" + p)
            if replica_cfg:
                cfg = replica_cfg
        if cfg:
            connection_info[p] = cfg

    connection_info.update(_HEALTH_PARAMS)
    return db_or_uri, connection_info
