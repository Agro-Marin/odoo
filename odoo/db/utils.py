import os
import re
import warnings
from urllib.parse import parse_qsl, urlsplit

import psycopg
from psycopg.adapt import Loader

from odoo import tools

# Emit the ODOO_PGAPPNAME deprecation at most once per process: db_connect()
# (which calls connection_info_for) runs repeatedly across a process's life —
# per cron job, per log flush, and from odoo.service.db — so an unguarded warn()
# would keep re-firing.
_ODOO_PGAPPNAME_WARNED = False


# Converts PostgreSQL numeric/decimal to Python float (Odoo convention).
# float loses precision vs Decimal, but the whole stack (ORM, reports, JS
# client) assumes float.  psycopg3 never calls load() with None.
class _NumericToFloatLoader(Loader):
    def load(self, data: bytes) -> float:
        return float(data)


def register_adapters(conn: psycopg.Connection) -> None:
    """Register Odoo's psycopg type adapters on a single connection.

    Per-connection (from the pool's ``configure`` callback), not on the
    process-global ``psycopg.adapters``: a module import must not change numeric
    decoding for other psycopg users in the process.  Odoo's connections all
    come from the pool, so they all get it; nothing else does.

    :param conn: the freshly-created psycopg connection to configure.
    """
    conn.adapters.register_loader("numeric", _NumericToFloatLoader)


def is_maintenance_db(db_name: str) -> bool:
    """True for system/template databases Odoo must never hold connections to.

    An idle connection to a template blocks ``CREATE DATABASE ... TEMPLATE``
    ("source database is being accessed by other users"), so the pool both
    discards borrowed connections to these on cursor close
    (:meth:`Cursor._close`) and refuses to keep ``minconn`` warm connections
    to them (:meth:`ConnectionPool._get_or_create_pool`) — either alone is
    insufficient: psycopg_pool refills to ``min_size`` right after a discard.
    ``db_template`` is read per call (not frozen at import) so tests and
    runtime reconfiguration see the current value.
    """
    return db_name in ("template0", "template1", "postgres", tools.config["db_template"])


# Query categorization patterns — debug-stats only, not correctness.  The
# optional `"?` handles quoted identifiers; the optional schema prefix matches
# `public.res_users` / `"public"."res_users"`.  Misclassification only skews
# debug stats.
re_from = re.compile(
    r'\bfrom\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
re_into = re.compile(
    r'\binto\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
# Anchored (^) on purpose: an unanchored ``\bupdate\b`` would also hit the
# row-locking clause of ``SELECT ... FOR UPDATE`` (common in the ORM) and
# misfile reads as writes.  ``WITH ... UPDATE`` slips past the anchor and falls
# through to the from/other buckets — same approximation as before.
re_update = re.compile(
    r'^\s*update\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
re_delete = re.compile(r"^\s*delete\b", re.IGNORECASE)


def categorize_query(decoded_query: str) -> tuple[str, str] | tuple[str, None]:
    """Categorize a SQL query as 'from' (read), 'into' (write), or 'other'
    and extract the table name.

    Writes — INSERT, UPDATE, DELETE — all land in 'into' so the per-table
    debug stats show every write on one bucket: an UPDATE classified 'other'
    would be invisible, and a DELETE classified 'from' would read as a SELECT.

    :param decoded_query: The SQL query string to categorize
    :return: A tuple of (query_type, table_name) where query_type is 'from', 'into', or 'other'
    """
    # Anchored UPDATE/DELETE first: their bodies may contain INTO/FROM inside
    # subqueries or string literals that would mislead the unanchored searches.
    res_update = re_update.match(decoded_query)
    if res_update:
        return "into", res_update.group(1)

    if re_delete.match(decoded_query):
        res_from = re_from.search(decoded_query)  # DELETE FROM <table>
        return ("into", res_from.group(1)) if res_from else ("other", None)

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
    # Pin to 3.0 so psycopg accepts the downgrade when PgBouncer (which only
    # speaks 3.0) sits between Odoo and PG18.
    "min_protocol_version": "3.0",
}


def connection_info_for(db_or_uri: str, readonly: bool = False) -> tuple[str, dict]:
    """Parse *db_or_uri* into a ``(dbname, connection_params)`` tuple.

    ``connection_params`` is either ``{"dsn": <URI>}`` or a dict of psycopg
    connection keywords.

    :param str db_or_uri: database name or postgres dsn
    :param bool readonly: load defaults from ``db_replica_*`` instead of ``db_*``.
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
    # Manual interpolation (security), trimmed to the default NAMEDATALEN=63.
    app_name = app_name.replace("{pid}", str(os.getpid()))[:63]

    if db_or_uri.startswith(("postgresql://", "postgres://")):
        # extract db from uri
        us = urlsplit(db_or_uri)
        if len(us.path) > 1:
            db_name = us.path[1:]
        elif us.username:
            db_name = us.username
        else:
            # No path and no username: malformed URI.  Falling back to the
            # hostname as the dbname label is almost certainly wrong — warn.
            warnings.warn(
                f"PostgreSQL URI {db_or_uri!r} has no database path and no "
                f"username; using hostname {us.hostname!r} as the database "
                f"name label.  This is likely a misconfiguration.",
                RuntimeWarning,
                stacklevel=2,
            )
            db_name = us.hostname
        # Only inject keys not already in the URI's query string: psycopg applies
        # kwargs over DSN values, so spreading _HEALTH_PARAMS blindly would
        # override an operator's explicit ?connect_timeout=60 (and application_name).
        uri_keys = {k for k, _ in parse_qsl(us.query)}
        merged = {k: v for k, v in _HEALTH_PARAMS.items() if k not in uri_keys}
        info = {"dsn": db_or_uri, **merged}
        if "application_name" not in uri_keys:
            info["application_name"] = app_name
        return db_name, info

    connection_info = {"dbname": db_or_uri, "application_name": app_name}
    for p in ("host", "port", "user", "password", "sslmode"):
        cfg = tools.config["db_" + p]
        # A read-only replica overrides only host/port (the only registered
        # ``db_replica_*`` options); a streaming replica shares the primary's
        # roles, so user/password/sslmode are inherited from ``db_*``.
        if readonly and p in ("host", "port"):
            replica_cfg = tools.config.get("db_replica_" + p)
            if replica_cfg:
                cfg = replica_cfg
        if cfg:
            connection_info[p] = cfg

    connection_info.update(_HEALTH_PARAMS)
    return db_or_uri, connection_info


def seed_planner_stats(cr, *, reltuples: float = 1000.0, relpages: int = 100) -> int:
    """Give zero-stat tables a plausible planner-statistics floor.

    Test suites roll back every transaction, so tables that only ever receive
    test data keep committed statistics of "empty" forever: ANALYZE (manual or
    autovacuum's) cannot see uncommitted rows, and ``pg_class.reltuples`` stays
    at 0 (vacuumed empty) or -1 (never analyzed). The planner then estimates
    ``rows=1`` for every scan of those tables and freely builds nested-loop
    chains whose join conditions degrade to late filters — effectively
    cartesian products that get quadratically slower as a long test
    transaction accumulates rows (observed in the sale suite:
    ``_compute_payment_state`` at 450ms/execution for 0 result rows, growing
    ~7ms per execution — the "test suite hang").

    Seeding ``reltuples``/``relpages`` floors via ``pg_restore_relation_stats``
    (PostgreSQL 18+, guaranteed by ``MIN_PG_VERSION``) keeps estimates
    non-trivial, so index conditions and sane join orders survive no matter how
    much uncommitted data a suite accumulates. Scope: ordinary ``public``
    tables owned by the current role with ``reltuples <= 0``. The floors are
    ordinary committed statistics — any later ANALYZE simply overwrites them.

    :param cr: cursor on the target database (the caller commits).
    :param reltuples: row-count floor to install.
    :param relpages: page-count floor to install.
    :return: number of tables seeded.
    """
    cr.execute(
        """
        SELECT count(*)
          FROM (
            SELECT pg_restore_relation_stats(
                       'schemaname', n.nspname::text,
                       'relname', c.relname::text,
                       'relpages', %s::integer,
                       'reltuples', %s::real
                   ) AS ok
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind = 'r'
               AND n.nspname = 'public'
               AND c.reltuples <= 0
               AND c.relowner = quote_ident(current_user)::regrole
          ) AS seeded
         WHERE seeded.ok
        """,
        (relpages, reltuples),
    )
    return cr.fetchone()[0]
