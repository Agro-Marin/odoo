import base64
import functools
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal
from xml.etree import ElementTree as ET

import psycopg

import odoo.api
import odoo.db
import odoo.modules.db
import odoo.modules.neutralize
import odoo.release
import odoo.tools
from odoo.release import version_info
from odoo.tools import SQL
from odoo.tools.misc import exec_pg_environ, find_pg_tool

from ._db_helpers import (
    DBNAME_MAX_LENGTH,
    DBNAME_PATTERN,
    SYSTEM_DBS,
    DatabaseExists,
    _drop_conn,
    check_db_management_enabled,
    check_super,
    database_identifier,
    validate_db_name,
)

from ._dump_scanner import (
    _assert_dump_sql_safe,
    _find_disallowed_psql_meta_command,
    _iter_physical_lines,
    _PsqlSqlScanner,
)
from ._env import env_float, env_int

if TYPE_CHECKING:
    from odoo.db import BaseCursor
else:
    BaseCursor = Any

_logger = logging.getLogger(__name__)

BACKUP_FORMATS = frozenset({"zip", "dump"})

__all__ = (
    "BACKUP_FORMATS",
    "DBNAME_MAX_LENGTH",
    "DBNAME_PATTERN",
    "SYSTEM_DBS",
    "DatabaseExists",
    "_drop_database",
    "_duplicate_database",
    "_rename_database",
    "check_db_management_enabled",
    "check_super",
    "database_identifier",
    "dispatch",
    "dump_db",
    "dump_db_manifest",
    "exp_change_admin_password",
    "exp_create_database",
    "exp_db_exist",
    "exp_drop",
    "exp_dump",
    "exp_duplicate_database",
    "exp_list",
    "exp_list_countries",
    "exp_list_lang",
    "exp_migrate_databases",
    "exp_rename",
    "exp_restore",
    "exp_server_version",
    "list_db_incompatible",
    "list_dbs",
    "restore_db",
    "validate_db_name",
)


def _check_faketime_mode(db_name: str) -> None:
    """Inject a clock-shifting ``public.now()`` into the DB for faketime tests.

    Gated on BOTH ``ODOO_FAKETIME_TEST_MODE`` AND ``test_enable`` (env-var-only
    would corrupt production timestamps on a stray export; ``test_enable``-only
    would fire on every test run), and only for databases named in ``db_name``.
    """
    if not os.getenv("ODOO_FAKETIME_TEST_MODE"):
        return
    if not odoo.tools.config["test_enable"]:
        _logger.warning(
            "ODOO_FAKETIME_TEST_MODE is set but --test-enable is not active. "
            "Refusing to install faketime now() into %r.",
            db_name,
        )
        return
    configured_dbs = odoo.tools.config["db_name"] or ()
    if db_name not in configured_dbs:
        return
    try:
        db = odoo.db.db_connect(db_name)
        with db.cursor() as cursor:
            cursor.execute("SELECT (pg_catalog.now() AT TIME ZONE 'UTC');")
            server_now = cursor.fetchone()[0]
            time_offset = (datetime.now() - server_now).total_seconds()

            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION public.now()
                    RETURNS timestamp with time zone AS $$
                        SELECT pg_catalog.now() +  %s * interval '1 second';
                    $$ LANGUAGE sql;
            """,
                (int(time_offset),),
            )
            cursor.execute("SELECT (now() AT TIME ZONE 'UTC');")
            new_now = cursor.fetchone()[0]
            _logger.info("Faketime mode, new cursor now is %s", new_now)
            cursor.commit()
    except psycopg.Error as e:
        _logger.warning("Unable to set faketime NOW(): %s", e)


def _warn_on_non_c_template(cr, template: str) -> None:
    """Warn when *template* would produce a database that is not ``LC_COLLATE=C``.

    The ``template0`` branch below pins ``LC_COLLATE 'C'`` explicitly, and the
    ORM leans on it: ``BaseModel.sorted()`` orders text by Python comparison
    while ``search(order=...)`` orders by the database's collation, and the two
    agree *only* because byte order and code-point order coincide under ``C``.
    A configured ``db_template`` that is not itself ``C`` propagates its own
    collation -- PostgreSQL refuses to override a template's collation, so this
    can be reported but not corrected here -- and every in-memory re-sort then
    silently stops reproducing the order the records were searched in.
    """
    cr.execute("SELECT datcollate FROM pg_database WHERE datname = %s", (template,))
    row = cr.fetchone()
    if row is not None and row[0] != "C":
        _logger.warning(
            "db_template %r has LC_COLLATE=%r, not 'C'; databases created from "
            "it inherit that collation, so SQL ORDER BY and in-memory "
            "recordset.sorted() will disagree on text. Rebuild the template "
            "from template0 with LC_COLLATE 'C' to restore the invariant.",
            template,
            row[0],
        )


def _create_empty_database(
    name: str,
    template: str | None = None,
    force_unaccent: bool = False,
    setup_if_exists: bool = True,
) -> None:
    """Create an empty database.

    Lets PostgreSQL be the source of truth for existence (a pre-flight
    ``SELECT`` is racy): attempt ``CREATE DATABASE`` directly and translate the
    duplicate-name error into the canonical ``DatabaseExists``.

    That error has TWO spellings and both must be caught.  A *sequential*
    duplicate raises ``42P04`` (``DuplicateDatabase``), but when callers race,
    the losers trip the unique index on ``pg_database.datname`` and get
    ``23505`` (``UniqueViolation``) instead — which is not a subclass of the
    former.  Catching only ``42P04`` therefore missed the exact concurrent case
    this pre-flight-free design exists to handle, and a racing caller of the
    ``auth``-gated ``exp_create_database`` received a raw psycopg error as an RPC
    Fault rather than ``DatabaseExists``.  Measured against a live PostgreSQL 18
    cluster: 10 trials x 4 racers produced 30 ``UniqueViolation`` and zero
    ``DuplicateDatabase``; the sequential duplicate produced ``42P04``.  Pinned
    against the real server by ``tests/contract/test_pg_create_database_race.py``
    — a mock cannot catch this, because the mock encodes the same wrong belief.

    ``CREATE DATABASE ... TEMPLATE t`` also needs zero sessions on ``t``, so it
    is retried through :func:`_retry_on_object_in_use` like the sibling
    database-level DDLs.  With the upstream default template this never fires —
    ``template0`` is ``datallowconn = false``, so nothing can be connected — but
    ``--db-template`` is documented and supported, and a populated template
    (this workspace's ``tpl_p314o19marin``) is ``datallowconn = true``: one
    ``psql`` session on it is enough to fail every database creation on the
    instance, including the auto-create-on-serve boot path.  Without the retry
    that surfaced as a raw ``psycopg.errors.ObjectInUse``.

    Unlike DROP / RENAME / DUPLICATE this deliberately does NOT terminate the
    blocking sessions (no ``_drop_conn``): those ops evict connections to a
    database they are about to destroy or rewrite, whereas the blocker here is a
    third party's session on a template this call only READS — very likely the
    operator maintaining it.  Backoff-only retries the transient case and leaves
    the deliberate one alone, failing with an error that names the template.

    :param template: override the configured ``db_template``. ``restore_db``
        passes ``"template0"``: a dump replay needs a bare canvas — any object
        a populated template pre-creates (e.g. ``orm_signaling_*``) collides
        with the dump's own copy and aborts the restore under ON_ERROR_STOP.
    :param force_unaccent: install and mark ``unaccent`` indexable regardless
        of ``config['unaccent']``. ``restore_db`` needs this: the *source*
        database decided whether unaccent expression indexes exist in the
        dump, and pg_dump cannot carry the IMMUTABLE marking of an
        extension-owned function — without it the replay fails with
        "functions in index expression must be marked IMMUTABLE".
    :param setup_if_exists: when the database already exists, whether to still
        run the idempotent extension/GRANT setup on it before raising
        ``DatabaseExists``.  ``True`` (default) suits the auto-create/serve path
        (``cli/server.py``, ``cli/start.py``): the operator may have pre-created
        a bare DB with ``createdb`` and Odoo must make it ready.  ``False`` suits
        the strict create/restore paths, where hitting an existing name is a
        *collision* on a database this call did not make and must not mutate
        (notably re-``GRANT``ing ``CREATE ON public``, which the owner may have
        deliberately revoked).
    """
    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        chosen_template = template or odoo.tools.config["db_template"]
        validate_db_name(chosen_template)
        cr.rollback()
        cr.connection.autocommit = True

        if chosen_template == "template0":
            create_sql = SQL(
                "CREATE DATABASE %s ENCODING 'unicode' LC_COLLATE 'C' TEMPLATE %s",
                database_identifier(cr, name),
                database_identifier(cr, chosen_template),
            )
        else:
            _warn_on_non_c_template(cr, chosen_template)
            create_sql = SQL(
                "CREATE DATABASE %s ENCODING 'unicode' TEMPLATE %s",
                database_identifier(cr, name),
                database_identifier(cr, chosen_template),
            )
        already_exists = False

        def _create() -> None:
            nonlocal already_exists
            try:
                cr.execute(create_sql, log_exceptions=False)
            except psycopg.errors.DuplicateDatabase, psycopg.errors.UniqueViolation:
                already_exists = True

        _retry_on_object_in_use(
            f"CREATE DB: {name} (template {chosen_template})", _create
        )

    if already_exists and not setup_if_exists:
        raise DatabaseExists(f"database {name!r} already exists!")

    try:
        db = odoo.db.db_connect(name)
        with db.cursor() as cr:
            cr.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            if force_unaccent or odoo.tools.config["unaccent"]:
                cr.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
                if (
                    odoo.modules.db.has_unaccent(cr)
                    != odoo.modules.db.FunctionStatus.INDEXABLE
                ):
                    cr.execute(
                        "ALTER FUNCTION unaccent(text) IMMUTABLE",
                        log_exceptions=False,
                    )
    except psycopg.Error as e:
        _logger.error(
            "Unable to create PostgreSQL extensions in %r: %s. "
            "Check that postgresql-contrib is installed and the DB role has "
            "CREATE EXTENSION privileges; without pg_trgm/unaccent, search "
            "queries on this database will fall back to slower paths.",
            name,
            e,
        )
    _check_faketime_mode(name)

    try:
        db = odoo.db.db_connect(name)
        with db.cursor() as cr:
            cr.execute("GRANT CREATE ON SCHEMA PUBLIC TO PUBLIC")
    except psycopg.Error as e:
        _logger.warning("Unable to make public schema public-accessible: %s", e)

    if already_exists:
        raise DatabaseExists(f"database {name!r} already exists!")


def _rollback_new_database(db_name: str, what: str) -> None:
    """Drop a half-built database after a create/restore/duplicate failure.

    Call from the population step's ``except``, then re-``raise``.  Uses the
    internal ``_drop_database`` (not ``exp_drop``, whose ``list_db`` re-check
    could orphan the DB if the flag toggled).  Drop failures are suppressed so
    they can't mask the original error.  ``what`` is an operator-facing tag.
    """
    _logger.info("%s: rolling back database %r after failure", what, db_name)
    with suppress(Exception):
        _drop_database(db_name)


def _assert_filestore_dest_free(dest: str, problem: str) -> None:
    """Pre-flight a name-creating op: refuse if its destination filestore exists.

    A leftover ``filestore/<name>/`` (failed drop, manual ``dropdb``, crashed
    restore) would silently bind the new database to foreign attachments.  Run
    before any DB-level work so a conflict leaves nothing to roll back.
    """
    if Path(dest).exists():
        raise RuntimeError(
            f"{problem}: destination filestore {dest!r} already exists.  "
            f"Move or delete the stale directory before retrying."
        )


@check_db_management_enabled
def exp_create_database(
    db_name: str,
    demo: bool,
    lang: str,
    user_password: str = "admin",
    login: str = "admin",
    country_code: str | None = None,
    phone: str | None = None,
) -> Literal[True]:
    """Create and initialize a new database.

    Rolls back the empty database on init failure (module install error, missing
    language, etc.) so the name can be reused, rather than leaving a valid PG
    database with no Odoo schema for the operator to drop by hand.
    """
    validate_db_name(db_name)
    _assert_filestore_dest_free(
        odoo.tools.config.filestore(db_name), f"Cannot create {db_name!r}"
    )
    _logger.info("Create database `%s`.", db_name)
    _create_empty_database(db_name, setup_if_exists=False)
    try:
        odoo.modules.db.initialize_db(
            db_name, demo, lang, user_password, login, country_code, phone
        )
    except Exception:
        _rollback_new_database(db_name, "CREATE DB")
        raise
    return True


@check_db_management_enabled
def exp_duplicate_database(
    db_original_name: str,
    db_name: str,
    neutralize_database: bool = False,
) -> Literal[True]:
    """Duplicate ``db_original_name`` to ``db_name`` (public/RPC-facing).

    Refuses ``db_original_name`` outside ``list_dbs(True)``, else the master
    password alone would let an RPC caller copy any database owned by this PG
    role.  ``db_name`` (the new target) is create-like and not checked.

    :raises odoo.exceptions.AccessDenied: if ``db_original_name`` is not exposed
    """
    check_db_exposed(db_original_name)
    return _duplicate_database(db_original_name, db_name, neutralize_database)


def _duplicate_database(
    db_original_name: str,
    db_name: str,
    neutralize_database: bool = False,
) -> Literal[True]:
    """Duplicate ``db_original_name`` to ``db_name`` (ungated internal helper).

    No gates here: both live on the RPC wrapper ``exp_duplicate_database``.  The
    shell-access ``odoo db duplicate`` CLI calls this directly (mirrors the
    ``_drop_database`` / ``exp_drop`` split).

    Uses ``CREATE DATABASE ... TEMPLATE ...``, which needs the source to have no
    active connections — hence the ``close_db`` + ``_drop_conn`` preamble.
    Forces a new dbuuid so the copy can coexist with the original; with
    ``neutralize_database=True`` also scrubs sensitive settings (SMTP, webhooks).
    On any failure after creation the empty database is dropped to free the name.
    """
    validate_db_name(db_name)

    to_fs = odoo.tools.config.filestore(db_name)
    _assert_filestore_dest_free(to_fs, f"Cannot duplicate to {db_name!r}")

    _logger.info("Duplicate database `%s` to `%s`.", db_original_name, db_name)
    odoo.db.close_db(db_original_name)
    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        cr.connection.autocommit = True

        def _create_from_template() -> None:
            try:
                cr.execute(
                    SQL(
                        "CREATE DATABASE %s ENCODING 'unicode' TEMPLATE %s",
                        database_identifier(cr, db_name),
                        database_identifier(cr, db_original_name),
                    )
                )
            except psycopg.errors.DuplicateDatabase as exc:
                raise DatabaseExists(f"database {db_name!r} already exists!") from exc

        _retry_terminate_then_ddl(
            cr,
            db_original_name,
            f"DUPLICATE DB: {db_original_name} -> {db_name}",
            _create_from_template,
        )

    try:
        registry = odoo.modules.registry.Registry.new(db_name)
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
            env["ir.config_parameter"].init(force=True)
            if neutralize_database:
                odoo.modules.neutralize.neutralize_database(cr)

        from_fs = odoo.tools.config.filestore(db_original_name)
        if Path(from_fs).exists():
            if Path(to_fs).exists():
                raise RuntimeError(
                    f"Filestore {to_fs!r} appeared between pre-flight and copy (race)."
                )
            shutil.copytree(from_fs, to_fs)
    except Exception:
        _rollback_new_database(db_name, "DUPLICATE DB")
        raise
    return True


_DROP_DATABASE_MAX_RETRIES = 5
_DROP_DATABASE_BACKOFF_BASE = 0.2


def _retry_on_object_in_use(
    op_label: str,
    run: Callable[[], None],
    *,
    before_attempt: Callable[[], None] | None = None,
) -> None:
    """Run a database-level DDL op, retrying while PG reports ``ObjectInUse``.

    Every ``CREATE``/``DROP``/``ALTER ... RENAME`` at the database level needs
    zero sessions on the database it reads or writes, and raises ``ObjectInUse``
    (55006) otherwise.  Because the sessions belong to other processes, that is a
    race rather than a permanent failure, so it is retried with exponential
    backoff instead of surfacing raw to the caller.

    ``before_attempt`` runs before each try; ``_retry_terminate_then_ddl``
    supplies the connection-eviction step for the ops that are entitled to it.
    ``run`` MUST let ``ObjectInUse`` propagate (so this loop retries) and may
    raise any other exception to abort immediately.  After the retries are
    exhausted the last ``ObjectInUse`` is re-raised wrapped in ``RuntimeError``,
    so callers see one actionable error type rather than a bare psycopg class.
    """
    last_error: psycopg.errors.ObjectInUse | None = None
    for attempt in range(1, _DROP_DATABASE_MAX_RETRIES + 1):
        if before_attempt is not None:
            before_attempt()
        try:
            run()
        except psycopg.errors.ObjectInUse as e:
            last_error = e
            _logger.info(
                "%s attempt %d/%d, still in use: %s",
                op_label,
                attempt,
                _DROP_DATABASE_MAX_RETRIES,
                e,
            )
            if attempt < _DROP_DATABASE_MAX_RETRIES:
                time.sleep(_DROP_DATABASE_BACKOFF_BASE * (2 ** (attempt - 1)))
        else:
            return
    raise RuntimeError(
        f"{op_label}: still in use after {_DROP_DATABASE_MAX_RETRIES} "
        f"attempts: {last_error}"
    ) from last_error


def _retry_terminate_then_ddl(
    cr: BaseCursor,
    terminate_target: str,
    op_label: str,
    run: Callable[[], None],
) -> None:
    """Terminate-then-act variant of :func:`_retry_on_object_in_use`.

    Used by DROP / DUPLICATE / RENAME, which are entitled to evict the sessions
    in their way: a connection to a database they are about to destroy or
    rewrite is already doomed.  The eviction re-runs on every attempt because a
    fresh request can reconnect before the DDL lands.

    CREATE deliberately does not use this variant — see
    :func:`_create_empty_database`.
    """
    _retry_on_object_in_use(
        op_label, run, before_attempt=lambda: _drop_conn(cr, terminate_target)
    )


_RESTORE_MAX_EXPANSION_RATIO = 50
_RESTORE_MIN_UNPACKED_BYTES = 100 * 1024 * 1024
_EXTRACT_CHUNK_BYTES = 1024 * 1024


def _extract_members_bounded(
    z: zipfile.ZipFile, members: list[str], dest: str, budget: int
) -> int:
    """Extract ``members`` into ``dest``, aborting once ``budget`` bytes are written.

    Replaces ``ZipFile.extractall``, which has no size ceiling.  Counts the bytes
    actually produced rather than trusting each member's declared ``file_size``,
    so a header that under-reports its own size buys nothing.  Returns the total
    written.

    Path safety is already established by the caller's ZipSlip check over
    ``namelist()`` — a superset of ``members`` — so this only has to create the
    parent directories.
    """
    dest_path = Path(dest)
    written = 0
    for member in members:
        info = z.getinfo(member)
        target = dest_path / member
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, target.open("wb") as out:
            while chunk := src.read(_EXTRACT_CHUNK_BYTES):
                written += len(chunk)
                if written > budget:
                    raise RuntimeError(
                        f"Refusing to restore: the archive expands to more than "
                        f"{budget} bytes, over {_RESTORE_MAX_EXPANSION_RATIO}x its "
                        f"compressed size. Raise "
                        f"ODOO_RESTORE_MAX_EXPANSION_RATIO if this backup is "
                        f"genuinely that compressible."
                    )
                out.write(chunk)
    return written


def _unpack_budget(dump_file: str) -> int:
    """Bytes ``restore_db`` will let an archive expand to (see the constants)."""
    ratio = env_int(
        "ODOO_RESTORE_MAX_EXPANSION_RATIO",
        _RESTORE_MAX_EXPANSION_RATIO,
        minimum=1,
        logger=_logger,
    )
    return max(Path(dump_file).stat().st_size * ratio, _RESTORE_MIN_UNPACKED_BYTES)


def _pg_dump_total_timeout() -> float:
    """Wall-clock ceiling (seconds) for any single ``pg_dump`` invocation.

    Shared by every dump path (blocking and streaming) so a hung ``pg_dump``
    (PG-side lock wait, unresponsive remote) can't block a worker forever.
    Default 1h; override via ``ODOO_PG_DUMP_TOTAL_TIMEOUT``.
    """
    return env_float("ODOO_PG_DUMP_TOTAL_TIMEOUT", 3600.0, logger=_logger)


def _pg_restore_total_timeout() -> float:
    """Wall-clock ceiling (seconds) for the ``psql``/``pg_restore`` invocation.

    Sibling of ``_pg_dump_total_timeout``, so a hung ``psql -f`` (lock wait,
    disk-full stall) raises a clean ``RuntimeError`` instead of blocking the
    worker until the master watchdog SIGKILLs it.  Default 1h; override via
    ``ODOO_PG_RESTORE_TOTAL_TIMEOUT``.
    """
    return env_float("ODOO_PG_RESTORE_TOTAL_TIMEOUT", 3600.0, logger=_logger)


def _drop_database(db_name: str) -> bool:
    """Internal DROP DATABASE helper for both ``exp_drop`` and cleanup paths.

    Ungated (no ``@check_db_management_enabled``, no ``list_dbs(True)`` check):
    both gates live on ``exp_drop``.  Cleanup callers (e.g. ``restore_db``
    rolling back a half-built DB that was never in the allowlist) must be able
    to bypass them — the reason this helper exists separately.

    Handles the terminate-then-drop race (``ObjectInUse`` / 55006 when another
    thread reconnects mid-drop) by retrying ``_DROP_DATABASE_MAX_RETRIES`` times.
    """
    try:
        probe = odoo.db.db_connect("postgres")
        with closing(probe.cursor()) as cr:
            cr.connection.autocommit = True
            cr.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,),
            )
            owner_row = cr.fetchone()
    except Exception:
        _logger.debug("DROP DB %r: existence probe failed", db_name, exc_info=True)
        owner_row = ()

    if owner_row is None:
        return False
    odoo.modules.registry.Registry.delete(db_name)
    odoo.db.close_db(db_name)

    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        cr.connection.autocommit = True

        def _drop() -> None:
            try:
                cr.execute(SQL("DROP DATABASE %s", database_identifier(cr, db_name)))
            except psycopg.errors.ObjectInUse:
                raise
            except Exception as e:
                _logger.info("DROP DB: %s failed:\n%s", db_name, e)
                raise RuntimeError(f"Couldn't drop database {db_name}: {e}") from e
            _logger.info("DROP DB: %s", db_name)

        _retry_terminate_then_ddl(cr, db_name, f"DROP DB: {db_name}", _drop)

    odoo.db.close_db(db_name)

    fs = odoo.tools.config.filestore(db_name)
    if Path(fs).exists():
        shutil.rmtree(fs)
    return True


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


@check_db_management_enabled
def exp_drop(db_name: str) -> bool:
    """Drop a database (public/RPC-facing, subject to ``list_db`` gate).

    Refuses any ``db_name`` outside ``list_dbs(True)`` through the same
    ``check_db_exposed`` its siblings use, else the master password alone would
    let an RPC caller drop any DB owned by this PG role.  The gate lives here,
    not in ``_drop_database``, which rollback callers must bypass.

    Refusal RAISES rather than returning ``False``, which is what disambiguates
    the return value: ``False`` now means one thing, "no such database".  It
    used to mean that OR "exists but is not exposed", and the web caller
    collapsed both into ``Database %r was not found`` — telling an operator a
    database they can see does not exist, while ``exp_dump`` answered Access
    Denied for the same name.  Returning ``False`` bought no secrecy either:
    ``drop`` requires the master password, and any caller holding it can
    enumerate outright via ``list``.

    :raises odoo.exceptions.AccessDenied: if ``db_name`` is not exposed
    :return: ``True`` if the database was dropped, ``False`` if it did not exist
    """
    check_db_exposed(db_name)
    return _drop_database(db_name)


@check_db_management_enabled
def exp_dump(db_name: str, backup_format: str) -> str:
    """Dump the database and return its base64-encoded content.

    Encodes in 3 MiB chunks against an on-disk tempfile, so the raw bytes never
    sit in memory; peak is still ~8N/3 (accumulator + final ``str`` during
    ``decode``), so a multi-GB dump doubles RSS — use ``dump_db(..., stream=...)``
    for true streaming.

    Note the web backup UI does NOT call this: it uses ``dump_db(name, None, ...)``
    and hands the temp file to werkzeug directly, avoiding the base64 round-trip.
    The only true-streaming caller is the ``odoo db dump`` CLI.
    """
    check_db_exposed(db_name)
    CHUNK_SIZE = 3 * 1024 * 1024
    encoded = bytearray()
    with tempfile.TemporaryFile(mode="w+b") as t:
        dump_db(db_name, t, backup_format)
        t.seek(0)
        while chunk := t.read(CHUNK_SIZE):
            encoded.extend(base64.b64encode(chunk))
    return encoded.decode("ascii")


@check_db_management_enabled
def dump_db_manifest(cr: BaseCursor) -> dict[str, Any]:
    """Return a dict describing the database content for a zip-format dump.

    The resulting ``manifest.json`` is written alongside the SQL dump and
    filestore, and is inspected at restore time to decide compatibility
    (Odoo version, installed modules with their db_version).
    """
    v = cr.connection.info.server_version
    pg_version = f"{v // 10000}.{v // 100 % 100}"
    cr.execute(
        "SELECT name, db_version FROM ir_module_module WHERE state = 'installed'"
    )
    modules = dict(cr.fetchall())
    return {
        "odoo_dump": "1",
        "db_name": cr.dbname,
        "version": odoo.release.version,
        "version_info": odoo.release.version_info,
        "major_version": odoo.release.major_version,
        "pg_version": pg_version,
        "modules": modules,
    }


def _run_pg_dump_blocking(cmd: list[str], env: dict, *, stdout: Any) -> None:
    """Run ``pg_dump`` to completion, raising ``RuntimeError`` on timeout/error.

    Used by the buffered custom-format path (``stream=None``), which needs the
    whole dump on disk before it can hand back a seekable file.  Every other dump
    path streams through :func:`_run_pg_dump_streaming`.  Bounded by
    ``_pg_dump_total_timeout`` so a hung pg_dump can't block a worker —
    ``subprocess.run`` kills and reaps.
    """
    timeout = _pg_dump_total_timeout()
    try:
        result = subprocess.run(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"pg_dump exceeded {timeout:.0f}s wall-clock timeout and was "
            f"terminated.  Set ODOO_PG_DUMP_TOTAL_TIMEOUT for slower DBs."
        ) from e
    if result.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace').strip()}"
        )


_STALL_SIGKILL_GRACE_S = 10.0

_STDERR_DRAIN_JOIN_S = 10.0


def _run_pg_dump_streaming(cmd: list[str], env: dict, stream: IO[bytes]) -> None:
    """Stream a custom-format ``pg_dump`` to ``stream`` while draining stderr.

    stdout is copied as produced; a sibling thread drains stderr so neither pipe
    blocks when pg_dump emits more than the OS pipe buffer of warnings.  A
    wall-clock ``Timer`` SIGTERMs a stalled pg_dump (``copyfileobj`` is otherwise
    unbounded if stdout EOF never arrives), and a bounded post-EOF wait escalates
    SIGTERM → SIGKILL.  Raises ``RuntimeError`` on stall or non-zero exit.
    """
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr_chunks: list[bytes] = []

    def _drain_stderr() -> None:
        try:
            while chunk := proc.stderr.read(4096):
                stderr_chunks.append(chunk)
        except OSError, ValueError:
            pass

    stderr_thread = threading.Thread(
        target=_drain_stderr, name="odoo.service.db.pg_dump.stderr", daemon=True
    )
    stderr_thread.start()

    total_timeout = _pg_dump_total_timeout()
    stall_killed = [False]

    def _kill_on_stall() -> None:
        stall_killed[0] = True
        _logger.error(
            "pg_dump exceeded total wall-clock timeout (%.0fs); sending SIGTERM",
            total_timeout,
        )
        with suppress(ProcessLookupError):
            proc.terminate()
        try:
            proc.wait(timeout=_STALL_SIGKILL_GRACE_S)
        except subprocess.TimeoutExpired:
            _logger.error(
                "pg_dump ignored SIGTERM %.0fs after stall; sending SIGKILL",
                _STALL_SIGKILL_GRACE_S,
            )
            with suppress(ProcessLookupError):
                proc.kill()

    stall_timer = threading.Timer(total_timeout, _kill_on_stall)
    stall_timer.daemon = True
    stall_timer.start()
    try:
        shutil.copyfileobj(proc.stdout, stream)
    finally:
        stall_timer.cancel()
        proc.stdout.close()
        stderr_thread.join(timeout=_STDERR_DRAIN_JOIN_S)
        if stderr_thread.is_alive():
            _logger.warning(
                "pg_dump stderr drain still running after %.0fs; leaving the "
                "pipe to the interpreter",
                _STDERR_DRAIN_JOIN_S,
            )
        else:
            proc.stderr.close()
        wait_timeout = env_float("ODOO_PG_DUMP_WAIT_TIMEOUT", 30.0, logger=_logger)
        try:
            proc.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            _logger.error(
                "pg_dump did not exit within %.0fs after stdout EOF; sending SIGTERM",
                wait_timeout,
            )
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _logger.error("pg_dump still alive; sending SIGKILL")
                proc.kill()
                proc.wait()
    stderr_output = b"".join(stderr_chunks)
    if stall_killed[0] and proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump exceeded {total_timeout:.0f}s wall-clock timeout and was "
            f"terminated.  Set ODOO_PG_DUMP_TOTAL_TIMEOUT for slower DBs."
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {proc.returncode}): "
            f"{stderr_output.decode(errors='replace').strip()}"
        )


def _zip_filestore_into(zipf: zipfile.ZipFile, filestore: str) -> None:
    """Add ``filestore``'s files to ``zipf`` under ``filestore/``, in place.

    Reads the LIVE filestore rather than a staged copy — see :func:`dump_db`.
    Symlinks are resolved and any target escaping ``filestore`` is skipped, so a
    stray link cannot pull arbitrary host files into a backup (the containment
    check :func:`osutil.zip_dir` performed, kept here now that the walk is ours).
    """
    root = Path(filestore)
    if not root.is_dir():
        return
    root_real = os.path.realpath(root)
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            fpath = Path(dirpath, fname)
            real = os.path.realpath(fpath)
            if not Path(real).is_file():
                continue
            if os.path.commonpath([root_real, real]) != root_real:
                _logger.warning(
                    "DUMP DB: skipping filestore entry %r, it resolves outside "
                    "the filestore (%r)",
                    str(fpath),
                    real,
                )
                continue
            zipf.write(fpath, str(Path("filestore", fpath.relative_to(root))))


def _write_zip_dump(
    db_name: str,
    stream: IO[bytes],
    cmd: list[str],
    env: dict,
    with_filestore: bool,
) -> None:
    """Write the v8+ zip backup of ``db_name`` straight into ``stream``.

    Members are produced in place — ``manifest.json``, ``dump.sql`` streamed from
    ``pg_dump``'s stdout through the deflater, then the filestore read where it
    lives.  Nothing is staged first: assembling the backup in a temporary
    directory charged a full copy of the filestore plus the uncompressed SQL to
    ``TMPDIR``, which is frequently a tmpfs and therefore to RAM.  Peak temp
    space is now the compressed archive alone, and only when ``stream`` is None.
    """
    with zipfile.ZipFile(
        stream, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as zipf:
        db = odoo.db.db_connect(db_name)
        with db.cursor() as cr:
            manifest = dump_db_manifest(cr)
        zipf.writestr("manifest.json", json.dumps(manifest, indent=4))
        # force_zip64 is mandatory, not defensive: streaming into a member
        # through ``ZipFile.open(..., "w")`` commits the local header before a
        # single byte is read, so zipfile cannot infer that the member needs
        # ZIP64 the way ``ZipFile.write()`` does from a stat().  Without it a
        # ``dump.sql`` that overruns 4 GiB raises "File size too large, try
        # using force_zip64" at member close — after minutes of dumping, and
        # only once the database grows past the threshold.  ``allowZip64`` on
        # the archive covers the central directory, not this.
        with zipf.open("dump.sql", "w", force_zip64=True) as sql_member:
            _run_pg_dump_streaming(cmd, env, sql_member)
        if with_filestore:
            _zip_filestore_into(zipf, odoo.tools.config.filestore(db_name))


@check_db_management_enabled
def dump_db(
    db_name: str,
    stream: IO[bytes] | None,
    backup_format: str = "zip",
    with_filestore: bool = True,
) -> IO[bytes] | None:
    """Dump database ``db_name`` into ``stream``; if ``stream`` is None,
    return a file object with the dump.

    .. warning::
        For the ``zip`` format this is a **best-effort online snapshot**, not a
        transactional one: ``pg_dump`` and the filestore read run in sequence, so
        writes landing in between are not captured coherently.  The SQL is taken
        FIRST and the filestore after, which makes the residue benign — a file
        with no row that references it, rather than a row whose file is missing.
        (The reverse order, which staging the filestore first used to impose,
        produced the broken direction.)  For a backup-of-record on a busy DB,
        freeze writes externally or use physical-replica snapshots.
    """
    validate_db_name(db_name)
    if backup_format not in BACKUP_FORMATS:
        raise ValueError(
            f"Invalid backup format {backup_format!r}: expected one of "
            f"{', '.join(sorted(BACKUP_FORMATS))}."
        )

    _logger.info(
        "DUMP DB: %s format %s %s",
        db_name,
        backup_format,
        "with filestore" if with_filestore else "without filestore",
    )

    cmd = [find_pg_tool("pg_dump"), "--no-owner", db_name]
    env = exec_pg_environ()

    if backup_format == "zip":
        if stream:
            _write_zip_dump(db_name, stream, cmd, env, with_filestore)
        else:
            t = tempfile.TemporaryFile()
            try:
                _write_zip_dump(db_name, t, cmd, env, with_filestore)
                t.seek(0)
            except BaseException:
                t.close()
                raise
            return t
    else:
        cmd.insert(-1, "--format=c")
        if stream:
            _run_pg_dump_streaming(cmd, env, stream)
        else:
            t = tempfile.TemporaryFile()
            try:
                _run_pg_dump_blocking(cmd, env, stdout=t)
                t.seek(0)
            except BaseException:
                t.close()
                raise
            return t
    return None


@check_db_management_enabled
def exp_restore(db_name: str, data: str, copy: bool = False) -> Literal[True]:
    """Restore a database from a base64-encoded dump string.

    ``data`` is the base64 body of a zip (v8+) or raw pg_dump custom format.
    Whitespace is tolerated: the accumulator below strips it per-chunk and
    buffers un-decoded chars so every ``b64decode`` gets a multiple of 4 chars
    (chunk boundaries landing mid-group on a 76-char wrap used to crash decoding).

    ``copy=True`` forces a new dbuuid so the restore can coexist with the original.
    """
    _STRIP_WS = str.maketrans("", "", " \t\n\r\v\f")
    CHUNK = 8192

    data_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        accum = ""
        for i in range(0, len(data), CHUNK):
            accum += data[i : i + CHUNK].translate(_STRIP_WS)
            n_complete = (len(accum) // 4) * 4
            if n_complete:
                data_file.write(base64.b64decode(accum[:n_complete]))
                accum = accum[n_complete:]
        if accum:
            data_file.write(base64.b64decode(accum))
        data_file.close()
        restore_db(db_name, data_file.name, copy=copy)
    finally:
        data_file.close()
        Path(data_file.name).unlink(missing_ok=True)
    return True


@check_db_management_enabled
def restore_db(
    db: str,
    dump_file: str,
    copy: bool = False,
    neutralize_database: bool = False,
) -> None:
    """Restore a database from a file on disk.

    Handles the v8+ zip format (SQL + filestore + manifest) and the raw pg_dump
    custom format.  On any failure after the empty DB is created,
    ``_drop_database`` frees the name.

    ``copy=True`` forces a new dbuuid; ``neutralize_database=True`` also scrubs
    external-integration config (SMTP, webhooks) for staging clones.

    Pre-flights the destination filestore: ``shutil.move`` into an existing
    directory would nest the dumped filestore inside a stale ``filestore/<db>/``,
    leaving ``ir.attachment`` rows resolving against the wrong tree.
    """
    if not isinstance(db, str):
        raise TypeError(f"db must be a str, got {type(db).__name__!r}")
    validate_db_name(db)
    if exp_db_exist(db):
        _logger.warning("RESTORE DB: %s already exists", db)
        raise RuntimeError(f"Database {db!r} already exists")

    fs_dest = odoo.tools.config.filestore(db)
    _assert_filestore_dest_free(fs_dest, f"Cannot restore to {db!r}")

    _logger.info("RESTORING DB: %s", db)
    _create_empty_database(
        db, template="template0", force_unaccent=True, setup_if_exists=False
    )

    filestore_path = None
    try:
        with tempfile.TemporaryDirectory() as dump_dir:
            if zipfile.is_zipfile(dump_file):
                with zipfile.ZipFile(dump_file, "r") as z:
                    dump_dir_resolved = Path(dump_dir).resolve()
                    for member in z.namelist():
                        target = (dump_dir_resolved / member).resolve()
                        if not target.is_relative_to(dump_dir_resolved):
                            raise RuntimeError(
                                f"Refusing to restore: archive member {member!r} "
                                f"escapes the extraction directory"
                            )

                    if "dump.sql" not in z.namelist():
                        raise RuntimeError(
                            "Refusing to restore: the archive contains no "
                            "'dump.sql' member, so it is not an Odoo database "
                            "backup."
                        )

                    filestore = [m for m in z.namelist() if m.startswith("filestore/")]
                    _extract_members_bounded(
                        z,
                        ["dump.sql"] + filestore,
                        dump_dir,
                        _unpack_budget(dump_file),
                    )

                    if filestore:
                        filestore_path = str(Path(dump_dir, "filestore"))

                dump_sql_path = str(Path(dump_dir, "dump.sql"))
                _assert_dump_sql_safe(dump_sql_path)

                pg_cmd = "psql"
                pg_args = [
                    "-q",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-f",
                    dump_sql_path,
                ]

            else:
                pg_cmd = "pg_restore"
                pg_args = ["--no-owner", "--exit-on-error", dump_file]

            _timeout = _pg_restore_total_timeout()
            try:
                r = subprocess.run(
                    [find_pg_tool(pg_cmd), "--dbname=" + db, *pg_args],
                    env=exec_pg_environ(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=_timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"Restore of {db!r} exceeded {_timeout:.0f}s wall-clock "
                    f"timeout and was terminated.  Set "
                    f"ODOO_PG_RESTORE_TOTAL_TIMEOUT for slower restores."
                ) from e
            if r.returncode != 0:
                _logger.error("RESTORE DB %r failed:\n%s", db, r.stderr)
                raise RuntimeError(
                    f"Couldn't restore database {db!r}:\n{r.stderr.strip()}"
                )

            registry = odoo.modules.registry.Registry.new(db)
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
                if copy:
                    env["ir.config_parameter"].init(force=True)
                if neutralize_database:
                    odoo.modules.neutralize.neutralize_database(cr)

                if filestore_path:
                    filestore_dest = env["ir.attachment"]._filestore()
                    if Path(filestore_dest).exists():
                        raise RuntimeError(
                            f"Filestore {filestore_dest!r} appeared between "
                            f"pre-flight and move (race)."
                        )
                    shutil.move(filestore_path, filestore_dest)

        _logger.info("RESTORE DB: %s", db)
    except Exception:
        _rollback_new_database(db, "RESTORE DB")
        raise


@check_db_management_enabled
def exp_rename(old_name: str, new_name: str) -> Literal[True]:
    """Rename ``old_name`` to ``new_name`` (public/RPC-facing).

    Refuses ``old_name`` outside ``list_dbs(True)``, else the master password
    alone would let an RPC caller rename any DB owned by this PG role.
    ``new_name`` (the target) is create-like and not checked.

    :raises odoo.exceptions.AccessDenied: if ``old_name`` is not exposed
    """
    check_db_exposed(old_name)
    return _rename_database(old_name, new_name)


def _rename_database(old_name: str, new_name: str) -> Literal[True]:
    """Rename a database (ungated internal helper; gates live on ``exp_rename``).

    No gates here: the shell-access ``odoo db rename`` CLI calls this directly
    (mirrors the ``_drop_database`` / ``exp_drop`` split).

    Validates ``new_name``, tears down the old registry and pool, issues ``ALTER
    DATABASE RENAME`` in autocommit (same ``ObjectInUse`` backoff retry as
    ``_drop_database``), then renames the filestore.  No new registry is built —
    the next request to ``new_name`` lazy-loads it.  Refuses pre-flight if the
    destination filestore exists.

    If ``shutil.move`` fails after the SQL rename, the DB is renamed back so DB
    and filestore stay in sync; if the rename-back also fails, both errors are
    raised together for manual intervention.
    """
    validate_db_name(new_name)

    old_fs = odoo.tools.config.filestore(old_name)
    new_fs = odoo.tools.config.filestore(new_name)
    _assert_filestore_dest_free(
        new_fs, f"Cannot rename database {old_name!r} to {new_name!r}"
    )

    odoo.modules.registry.Registry.delete(old_name)
    odoo.db.close_db(old_name)

    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        cr.connection.autocommit = True

        def _rename() -> None:
            try:
                cr.execute(
                    SQL(
                        "ALTER DATABASE %s RENAME TO %s",
                        database_identifier(cr, old_name),
                        database_identifier(cr, new_name),
                    )
                )
            except psycopg.errors.DuplicateDatabase as exc:
                raise DatabaseExists(f"database {new_name!r} already exists!") from exc
            except psycopg.errors.ObjectInUse:
                raise
            except Exception as e:
                _logger.info("RENAME DB: %s -> %s failed:\n%s", old_name, new_name, e)
                raise RuntimeError(
                    f"Couldn't rename database {old_name!r} to {new_name!r}: {e}"
                ) from e
            _logger.info("RENAME DB: %s -> %s", old_name, new_name)

        _retry_terminate_then_ddl(
            cr, old_name, f"RENAME DB: {old_name} -> {new_name}", _rename
        )

        if Path(old_fs).exists():
            if Path(new_fs).exists():
                _rollback_db_rename(cr, old_name, new_name)
                raise RuntimeError(
                    f"Filestore {new_fs!r} appeared between pre-flight and "
                    f"move (race).  Database rename rolled back."
                )
            try:
                shutil.move(old_fs, new_fs)
            except Exception as fs_err:
                _logger.error(
                    "RENAME DB: filestore move %r -> %r failed (%s); "
                    "rolling back DB rename",
                    old_fs,
                    new_fs,
                    fs_err,
                )
                try:
                    _rollback_db_rename(cr, old_name, new_name)
                except Exception as revert_err:
                    raise RuntimeError(
                        f"Couldn't rename filestore {old_fs!r} -> {new_fs!r} "
                        f"({fs_err}); ALSO failed to roll back DB rename "
                        f"{new_name!r} -> {old_name!r} ({revert_err}). "
                        f"Database and filestore are out of sync — manual "
                        f"intervention required."
                    ) from fs_err
                raise RuntimeError(
                    f"Couldn't rename filestore {old_fs!r} -> {new_fs!r}: "
                    f"{fs_err}. Database rename rolled back."
                ) from fs_err
    return True


def _rollback_db_rename(cr: BaseCursor, old_name: str, new_name: str) -> None:
    """Issue ``ALTER DATABASE new_name RENAME TO old_name``.

    Extracted so the rollback is identical for the filestore-move failure and
    the race-window case.
    """
    cr.execute(
        SQL(
            "ALTER DATABASE %s RENAME TO %s",
            database_identifier(cr, new_name),
            database_identifier(cr, old_name),
        )
    )


@check_db_management_enabled
def exp_change_admin_password(new_password: str) -> Literal[True]:
    """Set the master admin password.

    Enforces a minimum length — the master password authorises every destructive
    DB operation, so it is the highest-value credential.  Default 8 chars;
    ``ODOO_ADMIN_PASSWORD_MIN_LENGTH`` can raise (never lower) the floor for
    stricter regimes.  Further complexity checks belong in the HTTP controller.
    """
    if not isinstance(new_password, str):
        raise TypeError(
            f"new_password must be a str, got {type(new_password).__name__!r}"
        )
    min_length = env_int("ODOO_ADMIN_PASSWORD_MIN_LENGTH", 8, minimum=8)
    if len(new_password) < min_length:
        raise ValueError(
            f"Master admin password must be at least {min_length} characters long."
        )
    old_hash = odoo.tools.config.options.get("admin_passwd")
    odoo.tools.config.set_admin_password(new_password)
    try:
        odoo.tools.config.save(["admin_passwd"])
    except Exception:
        if old_hash is None:
            odoo.tools.config.options.pop("admin_passwd", None)
        else:
            odoo.tools.config.options["admin_passwd"] = old_hash
        _logger.exception(
            "Failed to persist admin password change; reverted in-memory hash"
        )
        raise
    _logger.info("Master admin password updated")
    return True


@check_db_management_enabled
def exp_migrate_databases(databases: list[str]) -> Literal[True]:
    """Run ``base`` module upgrade against each listed database.

    Used by the HTTP database-manager "Migrate" action to bring several
    databases forward one Odoo version at a time.
    """
    for db in databases:
        check_db_exposed(db)
    for db in databases:
        _logger.info("migrate database %s", db)
        odoo.modules.registry.Registry.new(
            db, update_module=True, upgrade_modules={"base"}
        )
    return True


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
    if db_name in SYSTEM_DBS or db_name == odoo.tools.config["db_template"]:
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
                if odoo.tools.sql.table_exists(cr, "ir_module_module"):
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
    root = ET.parse(
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


def dispatch(method: str, params: list[Any]) -> Any:
    """Dispatch a db-service RPC call, enforcing master password for admin ops.

    Single allowlist (``_DISPATCH``) for handler resolution, sister set
    (``_REQUIRES_MASTER_PASSWORD``) for auth — so no method can be both public
    and admin.  Unknown methods raise ``AttributeError``, uniform with
    ``common.dispatch`` / ``model.dispatch``.

    TRUST BOUNDARY: the master-password check lives HERE, at the RPC edge, not on
    the ``exp_*`` handlers.  A direct in-process call is trusted and bypasses the
    password, but is still gated by ``@check_db_management_enabled`` on the
    handler — keep destructive handlers decorated so that gate holds internally too.
    """
    handler = _DISPATCH.get(method)
    if handler is None:
        raise AttributeError(f"Method not found: {method}")
    if method in _REQUIRES_MASTER_PASSWORD:
        if not params:
            raise TypeError(
                f"{method} requires a master password as its first positional "
                f"argument; got 0 arguments."
            )
        passwd, *params = params
        check_super(passwd)
    return handler(*params)


_DISPATCH: dict[str, Callable] = {
    "db_exist": _rpc_db_exist,
    "list": exp_list,
    "list_lang": exp_list_lang,
    "server_version": exp_server_version,
    "create_database": exp_create_database,
    "duplicate_database": exp_duplicate_database,
    "drop": exp_drop,
    "dump": exp_dump,
    "restore": exp_restore,
    "rename": exp_rename,
    "change_admin_password": exp_change_admin_password,
    "migrate_databases": exp_migrate_databases,
    "list_countries": exp_list_countries,
}

_REQUIRES_MASTER_PASSWORD: frozenset[str] = frozenset(
    {
        "create_database",
        "duplicate_database",
        "drop",
        "dump",
        "restore",
        "rename",
        "change_admin_password",
        "migrate_databases",
    }
)
