import os
import re
import warnings
from urllib.parse import parse_qsl, urlsplit

import psycopg
from psycopg.adapt import Loader

from odoo import tools

_ODOO_PGAPPNAME_WARNED = False


class _NumericToFloatLoader(Loader):
    def load(self, data: bytes) -> float:
        return float(data)


def register_adapters(conn: psycopg.Connection) -> None:
    conn.adapters.register_loader("numeric", _NumericToFloatLoader)


SYSTEM_DBS = frozenset({"postgres", "template0", "template1"})


def is_maintenance_db(db_name: str) -> bool:
    return db_name in SYSTEM_DBS or db_name == tools.config["db_template"]


re_from = re.compile(
    r'\bfrom\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
re_into = re.compile(
    r'\binto\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
re_update = re.compile(
    r'^\s*update\s+(?:"?[a-zA-Z_0-9]+"?\.)?"?([a-zA-Z_0-9]+)\b', re.IGNORECASE
)
re_delete = re.compile(r"^\s*delete\b", re.IGNORECASE)


def categorize_query(decoded_query: str) -> tuple[str, str] | tuple[str, None]:
    res_update = re_update.match(decoded_query)
    if res_update:
        return "into", res_update.group(1)

    if re_delete.match(decoded_query):
        res_from = re_from.search(decoded_query)
        return ("into", res_from.group(1)) if res_from else ("other", None)

    res_into = re_into.search(decoded_query)
    if res_into:
        return "into", res_into.group(1)

    res_from = re_from.search(decoded_query)
    if res_from:
        return "from", res_from.group(1)

    return "other", None


_REPLICA_OVERRIDABLE: tuple[str, ...] = (
    "host",
    "port",
    "user",
    "password",
    "sslmode",
)

_HEALTH_PARAMS: dict[str, str] = {
    "connect_timeout": "10",
    "tcp_user_timeout": "30000",
    "keepalives": "1",
    "keepalives_idle": "60",
    "keepalives_interval": "10",
    "keepalives_count": "3",
    "min_protocol_version": "3.0",
}


def connection_info_for(db_or_uri: str, readonly: bool = False) -> tuple[str, dict]:
    global _ODOO_PGAPPNAME_WARNED  # noqa: PLW0603  warn-once latch for the whole process
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
    app_name = app_name.replace("{pid}", str(os.getpid()))[:63]

    if db_or_uri.startswith(("postgresql://", "postgres://")):
        us = urlsplit(db_or_uri)
        if len(us.path) > 1:
            db_name = us.path[1:]
        elif us.username:
            db_name = us.username
        else:
            warnings.warn(
                f"PostgreSQL URI {db_or_uri!r} has no database path and no "
                f"username; using hostname {us.hostname!r} as the database "
                f"name label.  This is likely a misconfiguration.",
                RuntimeWarning,
                stacklevel=2,
            )
            db_name = us.hostname or ""
        uri_keys = {k for k, _ in parse_qsl(us.query)}
        merged = {k: v for k, v in _HEALTH_PARAMS.items() if k not in uri_keys}
        info = {"dsn": db_or_uri, **merged}
        if "application_name" not in uri_keys:
            info["application_name"] = app_name
        return db_name, info

    connection_info = {"dbname": db_or_uri, "application_name": app_name}
    for p in _REPLICA_OVERRIDABLE:
        cfg = tools.config["db_" + p]
        if readonly:
            cfg = tools.config.get("db_replica_" + p) or cfg
        if cfg:
            connection_info[p] = cfg

    connection_info.update(_HEALTH_PARAMS)
    return db_or_uri, connection_info


def seed_planner_stats(cr, *, reltuples: float = 1000.0, relpages: int = 100) -> int:
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
