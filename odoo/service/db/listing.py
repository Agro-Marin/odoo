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
from odoo.release import version_info

from .._db_helpers import validate_db_name
from .._env import env_float

_logger = logging.getLogger("odoo.service.db")


_catalog_listeners: list[Callable[[], None]] = []


def register_catalog_listener(callback: Callable[[], None]) -> None:
    _catalog_listeners.append(callback)


def invalidate_catalog_caches() -> None:
    _forget_catalogue()
    for callback in _catalog_listeners:
        try:
            callback()
        except Exception:
            _logger.warning(
                "A database-catalogue listener failed; a cached database list "
                "may stay stale until its TTL expires.",
                exc_info=True,
            )


def check_db_exposed(db_name: str) -> None:
    if db_name not in list_dbs(True):
        _logger.warning(
            "DB management op on %s rejected, not in the list of exposed databases",
            db_name,
        )
        raise odoo.exceptions.AccessDenied


@odoo.tools.mute_logger("odoo.db")
def exp_db_exist(db_name: str) -> bool:
    try:
        db = odoo.db.db_connect(db_name)
        with db.cursor():
            return True
    except psycopg.errors.InvalidCatalogName:
        _logger.debug("exp_db_exist(%r): database does not exist", db_name)
        return False
    except Exception:
        _logger.info(
            "exp_db_exist(%r) returning False after non-existence error; "
            "may be transient (pool saturation, PG restart)",
            db_name,
            exc_info=True,
        )
        return False


def _rpc_db_exist(db_name: str) -> bool:
    if not odoo.tools.config["list_db"]:
        return False
    try:
        validate_db_name(db_name)
    except TypeError, ValueError:
        return False
    if is_maintenance_db(db_name):
        return False
    if db_name not in list_dbs(True):
        return False
    return exp_db_exist(db_name)


CATALOGUE_CACHE_TTL_S = 2.0

_catalogue_lock = threading.Lock()
_catalogue_cache: tuple[float, list[str]] | None = None


def _catalogue_ttl() -> float:
    return env_float(
        "ODOO_DB_CATALOGUE_CACHE_TTL",
        CATALOGUE_CACHE_TTL_S,
        minimum=0.0,
        logger=_logger,
    )


def _forget_catalogue() -> None:
    global _catalogue_cache  # noqa: PLW0603  one catalogue per process

    with _catalogue_lock:
        _catalogue_cache = None


def _query_catalogue() -> list[str] | None:
    """The catalogue, or None when PostgreSQL could not answer.

    The distinction matters to the cache: a transient failure answers `[]` to
    the caller -- this renders the database selector at auth=none, so it must
    not raise -- but caching that empty answer would blank the database list
    for the whole TTL over one hiccup.
    """
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
            return None


def _cached_catalogue() -> list[str]:
    """One pg_database scan serves every caller for a couple of seconds.

    The scan costs ~4.7ms and sits on the `db_exist` RPC that every client
    makes on connect, on `check_db_exposed` for every management operation, and
    on each cron sweep.  Anything this process does to the catalogue calls
    `invalidate_catalog_caches`, so the only staleness window is a database
    created or dropped by something *else* -- for at most the TTL, after which
    the next caller re-reads.  Set ODOO_DB_CATALOGUE_CACHE_TTL=0 to disable.
    """
    global _catalogue_cache  # noqa: PLW0603  one catalogue per process

    ttl = _catalogue_ttl()
    if ttl <= 0:
        return _query_catalogue() or []
    now = time.monotonic()
    with _catalogue_lock:
        cached = _catalogue_cache
        if cached is not None and now - cached[0] < ttl:
            return list(cached[1])
    names = _query_catalogue()
    if names is None:
        return []
    with _catalogue_lock:
        _catalogue_cache = (now, names)
    return list(names)


def list_dbs(force: bool = False) -> list[str]:
    if not odoo.tools.config["list_db"] and not force:
        raise odoo.exceptions.AccessDenied

    if not odoo.tools.config["dbfilter"] and odoo.tools.config["db_name"]:
        return sorted(odoo.tools.config["db_name"])

    return _cached_catalogue()


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
                        incompatible_databases.append(database_name)
                    else:
                        local_version = ".".join(base_version[0].split(".")[:2])
                        if local_version != server_version:
                            incompatible_databases.append(database_name)
                else:
                    incompatible_databases.append(database_name)
        except Exception:
            _logger.warning(
                "Could not check compatibility of database %r; treating it as "
                "incompatible",
                database_name,
                exc_info=True,
            )
            incompatible_databases.append(database_name)
    for database_name in databases:
        if database_name in incompatible_databases or database_name not in preexisting:
            odoo.db.close_db(database_name)
    return incompatible_databases


def exp_list(document: bool = False) -> list[str]:
    return list_dbs()


def exp_list_lang() -> list:
    return odoo.tools.misc.scan_languages()


@functools.cache
def _scan_countries() -> tuple[tuple[str, str], ...]:
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
    return tuple(sorted(countries, key=lambda c: c[1]))


def exp_list_countries() -> list[list[str]]:
    return [[code, name] for code, name in _scan_countries()]


def exp_server_version() -> str:
    return odoo.release.version
