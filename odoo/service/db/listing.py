import functools
import logging
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree as ET

import psycopg

import odoo.db
import odoo.release
import odoo.tools
from odoo.db import is_maintenance_db
from odoo.db import schema as _db_schema
from odoo.release import version_info

from .._db_helpers import validate_db_name

_logger = logging.getLogger("odoo.service.db")


_catalog_listeners: list[Callable[[], None]] = []


def register_catalog_listener(callback: Callable[[], None]) -> None:
    """Have *callback* run whenever this process changes the database catalogue.

    :func:`list_dbs` queries ``pg_database`` on every call, but its callers
    cache the answer -- ``odoo.http`` holds a TTL cache of the filtered list on
    the busiest path there is. Nothing told those caches when a database was
    created, dropped, renamed or restored *by this very process*, so the only
    thing that ever expired them was the TTL, and a freshly created database
    stayed invisible to the database selector for the length of it.

    Registered from above rather than called from here: ``odoo.http`` may import
    ``odoo.service.db``, and the reverse would be a cycle. Same shape as
    ``service.transaction.current_retry_participant``.
    """
    _catalog_listeners.append(callback)


def invalidate_catalog_caches() -> None:
    """Run every registered listener, swallowing what each one raises.

    Called from the database mutators; a listener that fails must not turn a
    completed ``CREATE DATABASE`` into an exception the caller sees.
    """
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
    """Return True iff a connection to ``db_name`` succeeds.

    Weaker than "the database exists": an existing-but-inaccessible DB (perm
    denied, pool saturated) returns False — the right semantic for the DB-manager
    wizard and RPC callers, which care whether Odoo can use it.

    The False return is undifferentiated, but the cause is logged so operators
    can tell "really doesn't exist" (``InvalidCatalogName``, DEBUG) from a
    transient PG issue (INFO, visible without enabling DEBUG).
    """
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


def list_dbs(force: bool = False) -> list[str]:
    """Databases this instance is willing to expose.

    Two paths, and the difference matters to callers:

    * ``db_name`` set (``-d``) with no ``dbfilter`` -- the configured names are
      returned VERBATIM.  The catalogue is never consulted, so a name whose
      database was dropped (or never created) is still returned.  ``-d`` is an
      operator ASSERTION about what this instance serves, not a check that it
      exists; the fast path exists precisely so a pinned deployment needs no
      connection to ``postgres`` to answer.
    * otherwise -- the real catalogue, filtered to databases this PG role owns.

    ``check_db_exposed`` gates on membership of this list, so on the first path
    it admits a name whose database is gone; the operation behind it then fails
    on its own when it cannot connect.  ``_rpc_db_exist`` does NOT inherit that
    looseness: it ends at ``exp_db_exist``, which opens a connection, and so
    answers ``False`` for a dead name either way.
    """
    if not odoo.tools.config["list_db"] and not force:
        raise odoo.exceptions.AccessDenied

    if not odoo.tools.config["dbfilter"] and odoo.tools.config["db_name"]:
        return sorted(odoo.tools.config["db_name"])

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
            return []


def list_db_incompatible(databases: list[str]) -> list[str]:
    """Check a list of databases for compatibility with this version of Odoo.

    Leaves the process's connection pools as it found them.  This is an
    INSPECTION helper reached from an ``auth="none"`` page (the database
    manager / selector calls it on every render, via
    ``web.controllers.database._render_template``), so it must not evict a pool
    that something else is using: each eviction costs the next request to that
    database a full pool rebuild — measured at ~4.9 ms versus ~0.24 ms on a warm
    pool, for every database on the instance, on every render.

    So a pool is closed only when this call is the reason it exists (probing a
    database nobody was serving — leaving that pool behind would be a leak), or
    when the database turns out to be INCOMPATIBLE and therefore will not be
    served anyway.  A compatible database that already had a pool keeps it.

    In-flight work was never at risk either way — a checked-out connection
    survives its pool's close, and registries are untouched — so the whole cost
    of the old unconditional close was reconnect latency.

    :param databases: A list of existing Postgresql databases
    :return: A list of databases that are incompatible
    """
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
    """RPC entry point for ``list_dbs``. Raises ``AccessDenied`` if ``list_db`` is off.

    ``document`` is kept for backward compatibility with older XML-RPC clients
    but has no effect.
    """
    return list_dbs()


def exp_list_lang() -> list:
    """Return ``(code, name)`` pairs for every installable language."""
    return odoo.tools.misc.scan_languages()


@functools.cache
def _scan_countries() -> tuple[tuple[str, str], ...]:
    root = ET.parse(  # noqa: S314  parses Odoo's own res_country_data.xml from root_path
        Path(odoo.tools.config.root_path, "addons/base/data/res_country_data.xml")
    ).getroot()
    countries = []
    for country in root.findall('.//record[@model="res.country"]'):
        name = country.find('field[@name="name"]').text
        code = country.find('field[@name="code"]').text
        countries.append((code, name))
    return tuple(sorted(countries, key=lambda c: c[1]))


def exp_list_countries() -> list[list[str]]:
    """Return ``[code, name]`` pairs for every country shipped in ``res.country`` XML.

    Reads the bundled XML directly rather than querying a database so it
    works before any DB exists (the DB-creation wizard needs this list
    on the pre-database selector page).  The parse is memoized in
    :func:`_scan_countries`; this builds the fresh mutable result each call.
    """
    return [[code, name] for code, name in _scan_countries()]


def exp_server_version() -> str:
    """Return the version of the server
    Used by the client to verify the compatibility with its own version
    """
    return odoo.release.version
