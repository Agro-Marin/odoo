"""Which databases exist, which are exposed, and the static lists beside them.

One of the five modules ``service/db.py`` was split into; the package
``__init__`` carries the shape and the dependency direction.
"""

import functools
import logging
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

# The log channel stays "odoo.service.db" across the split: operators and
# log-reading tests key on it, and _db_helpers / _dump_scanner already spell
# it literally for the same reason.
_logger = logging.getLogger("odoo.service.db")


def check_db_exposed(db_name: str) -> None:
    """Raise ``AccessDenied`` if ``db_name`` is not an exposed database.

    Shared allowlist gate for the master-password RPC handlers that act on an
    existing DB by name (``exp_dump``, ``exp_rename``, ``exp_duplicate_database``,
    ``exp_migrate_databases``).

    :raises odoo.exceptions.AccessDenied: if ``db_name`` is not exposed
    """
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
    """RPC-facing ``db_exist``: answers only for databases this instance exposes.

    Unexposed-but-existing names answer ``False``, indistinguishable by design
    from names that do not exist.  ``exp_db_exist`` stays ungated for in-process
    callers, the same split as ``_drop_database``/``exp_drop``.

    The gate matters because this verb is reachable unauthenticated: ungated it
    is a per-name existence oracle over every database owned by the PG role, and
    ``exp_db_exist`` connects, so a probe loop would also leave a pool resident
    per name.  Membership is ``list_dbs(True)`` so exposure rules cannot drift
    from ``check_db_exposed``.

    Deliberately not wrapped in ``check_db_management_enabled``: that raises
    ``AccessDenied`` when ``list_db = False``, which would turn a verb
    contracted to return a bool into one that raises for every input.
    """
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
    """List databases visible to this Odoo instance.

    1. ``AccessDenied`` unless ``list_db=True`` or ``force=True``.
    2. If ``--dbfilter`` is unset and ``--database`` is set, return that list
       as-is (explicit allowlist, PG roundtrip skipped).
    3. Otherwise query ``pg_database`` for DBs owned by the current PG role —
       how shared PG servers keep instances from enumerating each other (give
       each instance its own role for isolation).

    ``postgres`` and the configured template are excluded from the result.
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
    """Parse the bundled ``res.country`` XML once per process.

    A shipped data file under ``config.root_path`` cannot change while the
    process runs, and ``list_countries`` is an unauthenticated RPC verb, so an
    uncached parse re-read the XML on every anonymous call.

    Returns tuples so the cached value cannot be mutated by a caller;
    :func:`exp_list_countries` restores the list-of-lists its RPC contract
    promises.
    """
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
