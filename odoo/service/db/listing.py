import functools
import logging
import threading
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree as ET

import psycopg

import odoo.db
import odoo.exceptions
import odoo.release
import odoo.tools
from odoo.db import is_maintenance_db
from odoo.db import schema as _db_schema
from odoo.libs.debug_log import DebugLog
from odoo.release import version_info

from .._env import get_env_float
from ._checks import check_db_name

_logger = logging.getLogger("odoo.service.db")
_debug = DebugLog(__name__)


_catalog_listeners: list[Callable[[], None]] = []


def register_catalog_listener(callback: Callable[[], None]) -> None:
    _catalog_listeners.append(callback)
    _debug.lifecycle(
        "database.catalog_listener_registered",
        listener=getattr(callback, "__qualname__", None),
        listeners=len(_catalog_listeners),
    )


def invalidate_catalog_caches() -> None:
    _invalidate_catalog_cache()
    _debug.lifecycle(
        "database.catalog_invalidated",
        generation=_catalog_generation,
        listeners=len(_catalog_listeners),
    )
    for callback in _catalog_listeners:
        try:
            callback()
        except Exception:
            _logger.warning(
                "A database-catalogue listener failed; a cached database list "
                "may stay stale until its TTL expires.",
                exc_info=True,
            )
            _debug.logic(
                "database.catalog_listener_failed",
                listener=getattr(callback, "__qualname__", None),
            )


def check_db_exposed(db_name: str) -> None:
    if db_name not in list_dbs(True):
        _logger.warning(
            "DB management op on %s rejected, not in the list of exposed databases",
            db_name,
        )
        _debug.logic("database.not_exposed", db=db_name)
        raise odoo.exceptions.AccessDenied


@odoo.tools.mute_logger("odoo.db")
def exp_db_exist(db_name: str) -> bool:
    try:
        db = odoo.db.db_connect(db_name)
        with db.cursor():
            return True
    except psycopg.errors.InvalidCatalogName:
        _logger.debug("exp_db_exist(%r): database does not exist", db_name)
        _debug.logic("database.exist_probe", db=db_name, exists=False, reason="missing")
        return False
    except Exception:
        _logger.info(
            "exp_db_exist(%r) returning False after non-existence error; "
            "may be transient (pool saturation, PG restart)",
            db_name,
            exc_info=True,
        )
        _debug.logic("database.exist_probe", db=db_name, exists=False, reason="error")
        return False


def _rpc_db_exist(db_name: str) -> bool:
    if not odoo.tools.config["list_db"]:
        _debug.logic("database.exist_rpc_refused", reason="list_db_disabled")
        return False
    try:
        check_db_name(db_name)
    except TypeError, ValueError:
        _debug.logic("database.exist_rpc_refused", reason="invalid_name")
        return False
    if is_maintenance_db(db_name):
        _debug.logic("database.exist_rpc_refused", db=db_name, reason="maintenance")
        return False
    if db_name not in list_dbs(True):
        _debug.logic("database.exist_rpc_refused", db=db_name, reason="not_listed")
        return False
    if _is_db_list_configured():
        return exp_db_exist(db_name)
    return True


CATALOG_CACHE_TTL_S = 2.0

_catalog_lock = threading.Lock()
_catalog_cache: tuple[float, list[str]] | None = None

_catalog_generation = 0
"""Bumped by every invalidation, so a query in flight can tell it was outrun.

Dropping the cache is not enough on its own: `_get_catalog_cached` runs the
`pg_database` scan OUTSIDE the lock, so a create/drop/rename that invalidates
while a scan is travelling back would be undone the moment that scan stored
its pre-change list -- and the stale list would then be served for a full TTL.
The writer compares the generation it read before querying against the one it
finds after, and declines to cache a result that an invalidation has outrun.
"""


def _get_catalog_ttl() -> float:
    return get_env_float(
        "ODOO_DB_CATALOGUE_CACHE_TTL",
        CATALOG_CACHE_TTL_S,
        minimum=0.0,
        logger=_logger,
    )


def _invalidate_catalog_cache() -> None:
    global _catalog_cache, _catalog_generation  # noqa: PLW0603  one catalogue per process

    with _catalog_lock:
        _catalog_cache = None
        _catalog_generation += 1


def _get_catalog_uncached() -> list[str] | None:
    chosen_template = odoo.tools.config["db_template"]
    templates_list = tuple({"postgres", chosen_template})
    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        try:
            cr.execute(
                """
                SELECT datname
                  FROM pg_database
                 WHERE datdba = (SELECT usesysid FROM pg_user
                                  WHERE usename = current_user)
                   AND NOT datistemplate
                   AND datallowconn
                   AND datname != ALL(%s)
                 ORDER BY datname
                """,
                (list(templates_list),),
            )
            return [name for (name,) in cr.fetchall()]
        except Exception:
            _logger.exception("Listing databases failed:")
            _debug.logic("database.catalog_query_failed")
            return None


def _get_catalog_cached() -> list[str]:
    global _catalog_cache  # noqa: PLW0603  one catalogue per process

    ttl = _get_catalog_ttl()
    if ttl <= 0:
        _debug.logic("database.catalog_uncached", ttl=ttl)
        return _get_catalog_uncached() or []
    now = time.monotonic()
    with _catalog_lock:
        cached = _catalog_cache
        if cached is not None and now - cached[0] < ttl:
            return list(cached[1])
        generation = _catalog_generation
    with _debug.perf("database.catalog_listed", ttl=ttl) as span:
        names = _get_catalog_uncached()
        span.set(databases=None if names is None else len(names))
    if names is None:
        return []
    with _catalog_lock:
        if _debug.logic.enabled and _catalog_generation != generation:
            _debug.logic(
                "database.catalog_result_outrun",
                generation=generation,
                current=_catalog_generation,
            )
        if _catalog_generation == generation:
            _catalog_cache = (now, names)
    return list(names)


def _is_db_list_configured() -> bool:
    return not odoo.tools.config["dbfilter"] and bool(odoo.tools.config["db_name"])


def list_dbs(force: bool = False) -> list[str]:
    if not odoo.tools.config["list_db"] and not force:
        _debug.logic("database.list_refused", reason="list_db_disabled")
        raise odoo.exceptions.AccessDenied

    if _is_db_list_configured():
        _debug.logic("database.list_source", source="db_name")
        return sorted(odoo.tools.config["db_name"])

    return _get_catalog_cached()


def list_db_incompatible(databases: list[str]) -> list[str]:
    incompatible_databases = []
    server_version = ".".join(str(v) for v in version_info[:2])
    preexisting = {name for name in databases if odoo.db.is_pooled(name)}
    for database_name in databases:
        try:
            with closing(odoo.db.db_connect(database_name).cursor()) as cr:
                if _db_schema.table_exists(cr, "ir_module_module"):
                    cr.execute(
                        "SELECT db_version FROM ir_module_module WHERE name=%s",
                        ("base",),
                    )
                    base_version = cr.fetchone()
                    if not base_version or not base_version[0]:
                        _debug.logic(
                            "database.incompatible",
                            db=database_name,
                            reason="no_version",
                        )
                        incompatible_databases.append(database_name)
                    else:
                        local_version = ".".join(base_version[0].split(".")[:2])
                        if local_version != server_version:
                            _debug.logic(
                                "database.incompatible",
                                db=database_name,
                                reason="version",
                                local=local_version,
                                server=server_version,
                            )
                            incompatible_databases.append(database_name)
                else:
                    _debug.logic(
                        "database.incompatible", db=database_name, reason="no_table"
                    )
                    incompatible_databases.append(database_name)
        except Exception:
            _logger.warning(
                "Could not check compatibility of database %r; treating it as "
                "incompatible",
                database_name,
                exc_info=True,
            )
            _debug.logic("database.incompatible", db=database_name, reason="error")
            incompatible_databases.append(database_name)
    for database_name in databases:
        if database_name in incompatible_databases or database_name not in preexisting:
            odoo.db.close_db(database_name)
    _debug.pipeline(
        "database.compatibility_checked",
        databases=len(databases),
        incompatible=len(incompatible_databases),
        server_version=server_version,
    )
    return incompatible_databases


def exp_list(document: bool = False) -> list[str]:
    return list_dbs()


def exp_list_lang() -> list:
    return odoo.tools.misc.get_languages()


@functools.cache
def _read_countries() -> tuple[tuple[str, str], ...]:
    with _debug.perf("database.countries_read") as span:
        root = ET.parse(  # noqa: S314  parses Odoo's own res_country_data.xml from root_path
            Path(odoo.tools.config.root_path, "addons/base/data/res_country_data.xml")
        ).getroot()
        countries: list[tuple[str, str]] = []
        for country in root.findall('.//record[@model="res.country"]'):
            name = country.findtext('field[@name="name"]')
            code = country.findtext('field[@name="code"]')
            if code is None or name is None:
                continue
            countries.append((code, name))
        span.set(countries=len(countries))
    return tuple(sorted(countries, key=lambda c: c[1]))


def exp_list_countries() -> list[list[str]]:
    return [[code, name] for code, name in _read_countries()]


def exp_server_version() -> str:
    return odoo.release.version
