import base64
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
from odoo.libs.filesystem import osutil
from odoo.release import version_info
from odoo.tools import SQL
from odoo.tools.misc import exec_pg_environ, find_pg_tool

# Helpers live in a sibling module so this file stays focused on RPC entry
# points; re-exported below since external callers import them from here.
from ._db_helpers import (
    DBNAME_MAX_LENGTH,
    DBNAME_PATTERN,
    DatabaseExists,
    _drop_conn,
    check_db_management_enabled,
    check_super,
    database_identifier,
    validate_db_name,
)
from ._env import env_float, env_int

if TYPE_CHECKING:
    from odoo.db import BaseCursor
else:
    # PEP 649 introspects annotations at runtime, where importing ``BaseCursor``
    # from ``odoo.db`` would cycle through bootstrap; fall back to ``Any`` at
    # runtime while keeping the precise type for static analysis.
    BaseCursor = Any

_logger = logging.getLogger(__name__)

# Re-exported (definitions live in ``_db_helpers``) so ``from odoo.service.db
# import DBNAME_PATTERN`` etc. keep working; listing them makes the public
# surface explicit.
__all__ = (
    "DBNAME_MAX_LENGTH",
    "DBNAME_PATTERN",
    "DatabaseExists",
    # Underscore-prefixed but deliberately exported: the ungated, no-allowlist
    # DROP/DUPLICATE/RENAME primitives for callers with their own trust boundary
    # (``cli/db.py``'s shell-gated commands, create/restore rollback).  Not
    # RPC-facing — the exp_* wrappers are the gated public entry points.
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


# Database initialization has been moved to odoo.modules.db.initialize_db()


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
    # ``config['db_name']`` can be falsy (None / empty) when ``--database`` was
    # not passed; ``or ()`` avoids a ``TypeError`` from the ``in`` check below.
    configured_dbs = odoo.tools.config["db_name"] or ()
    if db_name not in configured_dbs:
        return
    try:
        db = odoo.db.db_connect(db_name)
        with db.cursor() as cursor:
            cursor.execute("SELECT (pg_catalog.now() AT TIME ZONE 'UTC');")
            server_now = cursor.fetchone()[0]
            # Intentionally uses local time: the offset aligns PG's
            # UTC clock with Python's (possibly faked) local clock.
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


def _create_empty_database(name: str) -> None:
    """Create an empty database.

    Lets PostgreSQL be the source of truth for existence (a pre-flight
    ``SELECT`` is racy): attempt ``CREATE DATABASE`` directly and translate PG's
    ``42P04`` (``DuplicateDatabase``) into the canonical ``DatabaseExists``.
    """
    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        chosen_template = odoo.tools.config["db_template"]
        # database-altering operations cannot be executed inside a transaction
        cr.rollback()
        cr.connection.autocommit = True

        # 'C' collate is only safe with template0 (and gives more useful
        # indexes); skip it on any other template.  Two explicit paths are
        # clearer than one parameterised fragment.
        if chosen_template == "template0":
            create_sql = SQL(
                "CREATE DATABASE %s ENCODING 'unicode' LC_COLLATE 'C' TEMPLATE %s",
                database_identifier(cr, name),
                database_identifier(cr, chosen_template),
            )
        else:
            create_sql = SQL(
                "CREATE DATABASE %s ENCODING 'unicode' TEMPLATE %s",
                database_identifier(cr, name),
                database_identifier(cr, chosen_template),
            )
        already_exists = False
        try:
            # log_exceptions=False: DuplicateDatabase is expected on the
            # auto-create path (``cli/server.py`` calls this unconditionally and
            # catches DatabaseExists); the default ERROR log would be misleading.
            cr.execute(create_sql, log_exceptions=False)
        except psycopg.errors.DuplicateDatabase:
            already_exists = True

    # Create the PG extensions Odoo relies on, on both the created and
    # already-existed paths (``IF NOT EXISTS`` is idempotent).  A DB pre-created
    # via ``createdb`` would otherwise lack ``pg_trgm``/``unaccent``, silently
    # degrading trigram-indexed searches.  Log at ERROR with the likely cause
    # (missing contrib package, insufficient privileges) so operators can act.
    try:
        db = odoo.db.db_connect(name)
        with db.cursor() as cr:
            cr.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            if odoo.tools.config["unaccent"]:
                cr.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
                # From PostgreSQL's point of view, making 'unaccent' immutable is incorrect
                # because it depends on external data - see
                # https://www.postgresql.org/message-id/flat/201012021544.oB2FiTn1041521@wwwmaster.postgresql.org#201012021544.oB2FiTn1041521@wwwmaster.postgresql.org
                # But in the case of Odoo, we consider that those data don't
                # change in the lifetime of a database. If they do change, all
                # indexes created with this function become corrupted!
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

    # PG 15+ revokes CREATE on the public schema by default; restore it for Odoo
    # (idempotent, and needed on the already-existed path too, else Odoo can't
    # create its own functions/types there).
    try:
        db = odoo.db.db_connect(name)
        with db.cursor() as cr:
            cr.execute("GRANT CREATE ON SCHEMA PUBLIC TO PUBLIC")
    except psycopg.Error as e:
        _logger.warning("Unable to make public schema public-accessible: %s", e)

    if already_exists:
        # Signal "already exists" to the caller (which decides drop-and-recreate
        # vs reuse).  Raised LAST so all idempotent setup has run on the existing
        # DB first.
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
    # Pre-flight the destination filestore, like duplicate/restore/rename.
    _assert_filestore_dest_free(
        odoo.tools.config.filestore(db_name), f"Cannot create {db_name!r}"
    )
    _logger.info("Create database `%s`.", db_name)
    _create_empty_database(db_name)
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
        # database-altering operations cannot be executed inside a transaction
        cr.connection.autocommit = True

        # ``CREATE DATABASE … TEMPLATE …`` needs zero sessions on the source.
        # ``_drop_conn`` is best-effort, and a fresh request between terminate
        # and CREATE causes ``ObjectInUse`` — retry with the same backoff as
        # ``_drop_database``.
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
                # Same ``DatabaseExists`` whether the collision happens here or in
                # ``_create_empty_database``.  (Other errors propagate to retry.)
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
            # if it's a copy of a database, force generation of a new dbuuid
            env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
            env["ir.config_parameter"].init(force=True)
            if neutralize_database:
                odoo.modules.neutralize.neutralize_database(cr)

        from_fs = odoo.tools.config.filestore(db_original_name)
        if Path(from_fs).exists():
            # Race-safe re-check: ``to_fs`` may have appeared since the pre-flight.
            # Surface a clear message and let the outer rollback drop the DB.
            if Path(to_fs).exists():
                raise RuntimeError(
                    f"Filestore {to_fs!r} appeared between pre-flight and copy (race)."
                )
            shutil.copytree(from_fs, to_fs)
    except Exception:
        _rollback_new_database(db_name, "DUPLICATE DB")
        raise
    return True


# Retry budget for the terminate-then-DDL loop.  A new HTTP request or cron tick
# can reconnect to the target DB between ``pg_terminate_backend`` and the DDL;
# retry with exponential backoff first.  The cumulative budget across 5 attempts
# (0.2+0.4+0.8+1.6+3.2 = 6.2s) covers a busy DB's connection-release worst case.
_DROP_DATABASE_MAX_RETRIES = 5
_DROP_DATABASE_BACKOFF_BASE = 0.2  # seconds; doubles each attempt


def _retry_terminate_then_ddl(
    cr: BaseCursor,
    terminate_target: str,
    op_label: str,
    run: Callable[[], None],
) -> None:
    """Run a database-level DDL op under the terminate-then-act retry loop
    shared by DROP / DUPLICATE / RENAME.

    These DDLs need zero sessions on the source/target; ``_drop_conn`` evicts
    them best-effort, but a fresh request can reconnect before the DDL, so PG
    raises ``ObjectInUse`` (55006).  Each attempt re-terminates and re-runs
    ``run`` with exponential backoff.

    ``run`` MUST let ``ObjectInUse`` propagate (so this loop retries) and may
    raise any other exception to abort immediately.  After the retries are
    exhausted the last ``ObjectInUse`` is re-raised wrapped in ``RuntimeError``.
    """
    last_error: psycopg.errors.ObjectInUse | None = None
    for attempt in range(1, _DROP_DATABASE_MAX_RETRIES + 1):
        _drop_conn(cr, terminate_target)
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
            # Don't sleep after the final attempt — it would only delay the
            # error, with no retry to follow.
            if attempt < _DROP_DATABASE_MAX_RETRIES:
                time.sleep(_DROP_DATABASE_BACKOFF_BASE * (2 ** (attempt - 1)))
        else:
            return
    raise RuntimeError(
        f"{op_label}: still in use after {_DROP_DATABASE_MAX_RETRIES} "
        f"attempts: {last_error}"
    ) from last_error


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
    # Existence check against ``pg_database`` itself, NOT ``list_dbs(True)``:
    # with ``--database`` and no ``--db-filter`` the latter returns the configured
    # allowlist, so a freshly-created DB outside it (a rollback target) would
    # look absent and this drop would silently no-op, orphaning it.  Autocommit
    # cursor on the maintenance DB so it never blocks on the target's txn state.
    try:
        probe = odoo.db.db_connect("postgres")
        with closing(probe.cursor()) as cr:
            cr.connection.autocommit = True
            cr.execute(
                "SELECT datdba::regrole FROM pg_database WHERE datname = %s",
                (db_name,),
            )
            owner_row = cr.fetchone()
    except Exception:
        # If the probe fails (e.g. no maintenance-DB access), fall through and
        # let DROP DATABASE surface the real error instead of returning False.
        _logger.debug("DROP DB %r: existence probe failed", db_name, exc_info=True)
        owner_row = ()  # sentinel: existence unknown -> attempt the drop

    if owner_row is None:
        # Genuinely absent from PostgreSQL: nothing to drop.
        return False
    odoo.modules.registry.Registry.delete(db_name)
    odoo.db.close_db(db_name)

    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        # database-altering operations cannot be executed inside a transaction
        cr.connection.autocommit = True

        def _drop() -> None:
            try:
                cr.execute(SQL("DROP DATABASE %s", database_identifier(cr, db_name)))
            except psycopg.errors.ObjectInUse:
                raise  # let _retry_terminate_then_ddl back off and retry
            except Exception as e:
                _logger.info("DROP DB: %s failed:\n%s", db_name, e)
                raise RuntimeError(f"Couldn't drop database {db_name}: {e}") from e
            _logger.info("DROP DB: %s", db_name)

        _retry_terminate_then_ddl(cr, db_name, f"DROP DB: {db_name}", _drop)

    # Close pools again: between the close_db above and the DROP, another thread
    # may have re-created a pool for this database.
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
    # Here, not beside check_super in _db_helpers: it needs ``list_dbs`` (this
    # module), and db.py imports from _db_helpers, not the reverse.
    if db_name not in list_dbs(True):
        _logger.warning(
            "DB management op on %s rejected, not in the list of exposed databases",
            db_name,
        )
        raise odoo.exceptions.AccessDenied


@check_db_management_enabled
def exp_drop(db_name: str) -> bool:
    """Drop a database (public/RPC-facing, subject to ``list_db`` gate).

    Refuses any ``db_name`` outside ``list_dbs(True)``, else the master password
    alone would let an RPC caller drop any DB owned by this PG role.  The gate
    lives here, not in ``_drop_database``, which rollback callers must bypass.
    """
    if db_name not in list_dbs(True):
        _logger.warning(
            "DROP DB: %s rejected, not in the list of exposed databases", db_name
        )
        return False
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
    # Multiple of 3 so each chunk encodes independently (base64 maps 3 bytes → 4
    # chars; a non-3-aligned chunk would emit padding mid-stream).
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

    Shared by the two blocking dump paths (zip, via ``--file=``; and buffered
    custom format to a ``TemporaryFile``).  Bounded by ``_pg_dump_total_timeout``
    so a hung pg_dump can't block a worker — ``subprocess.run`` kills and reaps.
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


# Grace (seconds) between the stall timer's SIGTERM and its follow-up SIGKILL in
# ``_run_pg_dump_streaming``: a fixed backstop for a pg_dump that ignores SIGTERM.
_STALL_SIGKILL_GRACE_S = 10.0


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
        while chunk := proc.stderr.read(4096):
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(
        target=_drain_stderr, name="odoo.service.db.pg_dump.stderr"
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
        # Escalate to SIGKILL if SIGTERM doesn't unblock the copy.  The ladder in
        # the ``finally`` below runs only after ``copyfileobj`` returns (stdout
        # EOF), but a wedged pg_dump never EOFs, so ``copyfileobj`` would block
        # forever.  Forcing SIGKILL from this Timer thread makes stdout EOF,
        # unblocking the copy so the ``finally`` can reap.  Concurrent
        # ``proc.wait`` is safe — CPython serialises waits and caches returncode.
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
        stderr_thread.join()
        # Bounded post-EOF wait + escalating signals; default 30s, override via
        # env.  ``env_float`` so a malformed value doesn't raise from this
        # ``finally`` (which would crash a successful dump / mask a failed one).
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
        # ``and proc.returncode != 0``: the stall timer and a clean finish can
        # race (EOF at returncode 0 just as the timer sets ``stall_killed``).  A
        # genuine kill leaves a negative returncode, so this gate avoids
        # reporting a successful dump as a spurious timeout.
        raise RuntimeError(
            f"pg_dump exceeded {total_timeout:.0f}s wall-clock timeout and was "
            f"terminated.  Set ODOO_PG_DUMP_TOTAL_TIMEOUT for slower DBs."
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {proc.returncode}): "
            f"{stderr_output.decode(errors='replace').strip()}"
        )


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
        transactional one: the manifest, then the filestore copytree, then
        ``pg_dump`` run in sequence, so writes during the copytree→pg_dump window
        yield inconsistent dumps (an attachment row without its file, or vice
        versa).  For a backup-of-record on a busy DB, freeze writes externally or
        use physical-replica snapshots.
    """
    # Same name shape/length guard as create/duplicate/rename/restore.  The name
    # is a trailing ``pg_dump`` argv positional, so an unvalidated value like
    # ``--jobs=…`` would be parsed as an option (argument injection — no shell,
    # not RCE).  The custom-format path has no ``db_connect`` to reject it first,
    # so guard here before any argv is built.
    validate_db_name(db_name)

    _logger.info(
        "DUMP DB: %s format %s %s",
        db_name,
        backup_format,
        "with filestore" if with_filestore else "without filestore",
    )

    cmd = [find_pg_tool("pg_dump"), "--no-owner", db_name]
    env = exec_pg_environ()

    if backup_format == "zip":
        with tempfile.TemporaryDirectory() as dump_dir:
            # Manifest first: its cursor is the cheapest touch of the source DB,
            # so an unreachable/bogus DB fails fast instead of after the (maybe
            # multi-GB) copytree.  Doesn't widen the copytree→pg_dump window.
            with Path(dump_dir, "manifest.json").open("w") as fh:
                db = odoo.db.db_connect(db_name)
                with db.cursor() as cr:
                    json.dump(dump_db_manifest(cr), fh, indent=4)
            if with_filestore:
                filestore = odoo.tools.config.filestore(db_name)
                if Path(filestore).exists():
                    shutil.copytree(filestore, Path(dump_dir, "filestore"))
            cmd.insert(-1, "--file=" + str(Path(dump_dir, "dump.sql")))
            _run_pg_dump_blocking(cmd, env, stdout=subprocess.DEVNULL)
            # ``dump.sql`` sorts last in the archive so a streaming consumer
            # sees the manifest and filestore before the (large) SQL body.
            dump_sql_last = lambda file_name: file_name != "dump.sql"  # noqa: E731
            if stream:
                osutil.zip_dir(
                    dump_dir, stream, include_dir=False, fnct_sort=dump_sql_last
                )
            else:
                t = tempfile.TemporaryFile()  # noqa: SIM115 (returned to caller)
                try:
                    osutil.zip_dir(
                        dump_dir, t, include_dir=False, fnct_sort=dump_sql_last
                    )
                    t.seek(0)
                except BaseException:
                    # Close on any abnormal exit so the OS fd isn't leaked to GC.
                    t.close()
                    raise
                return t
    else:
        cmd.insert(-1, "--format=c")
        if stream:
            _run_pg_dump_streaming(cmd, env, stream)
        else:
            # Buffer to a TemporaryFile so the caller gets a seekable object
            # and errors are detected before returning.
            t = tempfile.TemporaryFile()  # noqa: SIM115 (returned to caller)
            try:
                _run_pg_dump_blocking(cmd, env, stdout=t)
                t.seek(0)
            except BaseException:
                # Close on any abnormal exit so the OS fd is not leaked.
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
    # ``str.maketrans('', '', whitespace)`` deletes the listed chars; faster
    # than a regex or per-char filter on a multi-MB string.
    _STRIP_WS = str.maketrans("", "", " \t\n\r\v\f")
    CHUNK = 8192  # multiple of 4 — clean 4-char alignment after whitespace strip

    data_file = tempfile.NamedTemporaryFile(delete=False)  # noqa: SIM115 (path used after close)
    try:
        accum = ""
        for i in range(0, len(data), CHUNK):
            accum += data[i : i + CHUNK].translate(_STRIP_WS)
            n_complete = (len(accum) // 4) * 4
            if n_complete:
                data_file.write(base64.b64decode(accum[:n_complete]))
                accum = accum[n_complete:]
        if accum:
            # Final partial group (with padding) at end of input.
            data_file.write(base64.b64decode(accum))
        data_file.close()
        restore_db(db_name, data_file.name, copy=copy)
    finally:
        # Close before unlinking so the fd isn't leaked on the decode-error path
        # (which skips the ``close()`` above); ``close()`` is idempotent.
        data_file.close()
        # ``missing_ok`` so a racing deletion (tmp cleaner, concurrent admin)
        # doesn't turn a successful restore into a spurious FileNotFoundError.
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
    # Same name shape/length gate as create/duplicate/rename.
    validate_db_name(db)
    if exp_db_exist(db):
        _logger.warning("RESTORE DB: %s already exists", db)
        raise RuntimeError(f"Database {db!r} already exists")

    fs_dest = odoo.tools.config.filestore(db)
    _assert_filestore_dest_free(fs_dest, f"Cannot restore to {db!r}")

    _logger.info("RESTORING DB: %s", db)
    _create_empty_database(db)

    filestore_path = None
    try:
        with tempfile.TemporaryDirectory() as dump_dir:
            if zipfile.is_zipfile(dump_file):
                # v8 format
                with zipfile.ZipFile(dump_file, "r") as z:
                    # Explicit ZipSlip defense (belt-and-suspenders over
                    # extractall's own ``..`` stripping), holding even if a
                    # future edit switches to ``z.extract``.  Validated over
                    # member names, not extracted files, to keep it O(entries).
                    dump_dir_resolved = Path(dump_dir).resolve()
                    for member in z.namelist():
                        target = (dump_dir_resolved / member).resolve()
                        if not target.is_relative_to(dump_dir_resolved):
                            raise RuntimeError(
                                f"Refusing to restore: archive member {member!r} "
                                f"escapes the extraction directory"
                            )

                    # only extract known members!
                    filestore = [m for m in z.namelist() if m.startswith("filestore/")]
                    z.extractall(dump_dir, ["dump.sql"] + filestore)

                    if filestore:
                        filestore_path = str(Path(dump_dir, "filestore"))

                pg_cmd = "psql"
                # ``-v ON_ERROR_STOP=1`` is REQUIRED: without it ``psql -f``
                # exits 0 even when statements fail, so a broken dump would
                # restore a partial DB reported as success.  With it, psql exits
                # non-zero on the first ERROR and the rollback path fires.
                pg_args = [
                    "-q",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-f",
                    str(Path(dump_dir, "dump.sql")),
                ]

            else:
                # <= 7.0 format (raw pg_dump output)
                pg_cmd = "pg_restore"
                # ``--exit-on-error`` for the same reason as the zip path's
                # ``ON_ERROR_STOP=1``: pg_restore defaults to CONTINUE past
                # per-statement errors and exit 0, a silent partial restore.  The
                # target is a fresh empty DB, so this only bites a broken dump.
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
                # ``subprocess.run`` already killed and reaped the child; the
                # outer ``except`` drops the half-restored DB to free the name.
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
                    # if it's a copy of a database, force generation of a new dbuuid
                    env["ir.config_parameter"].init(force=True)
                if neutralize_database:
                    odoo.modules.neutralize.neutralize_database(cr)

                if filestore_path:
                    filestore_dest = env["ir.attachment"]._filestore()
                    # Race-safe re-check: ``filestore_dest`` may have appeared
                    # since the pre-flight, and ``shutil.move`` into an existing
                    # dir would nest ``src`` inside it (silent corruption).
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
        # database-altering operations cannot be executed inside a transaction
        cr.connection.autocommit = True

        # Same terminate-then-act race as DROP / DUPLICATE (a fresh request can
        # land between ``_drop_conn`` and the RENAME); retry with shared backoff.
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
                # Same ``DatabaseExists`` as the create / duplicate collisions.
                raise DatabaseExists(f"database {new_name!r} already exists!") from exc
            except psycopg.errors.ObjectInUse:
                raise  # let _retry_terminate_then_ddl back off and retry
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
            # Race-safe re-check: ``new_fs`` may have appeared since the
            # pre-flight, and ``shutil.move`` into an existing dir would nest
            # ``src`` inside it (silent corruption).
            if Path(new_fs).exists():
                _rollback_db_rename(cr, old_name, new_name)
                raise RuntimeError(
                    f"Filestore {new_fs!r} appeared between pre-flight and "
                    f"move (race).  Database rename rolled back."
                )
            try:
                shutil.move(old_fs, new_fs)
            except Exception as fs_err:
                # Roll the SQL rename back so DB and filestore stay aligned.
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
    # Silent (no ``logger``).  ``minimum=8`` is the hard floor: the env var can
    # only raise it, and a malformed value falls back to 8.
    min_length = env_int("ODOO_ADMIN_PASSWORD_MIN_LENGTH", 8, minimum=8)
    if len(new_password) < min_length:
        raise ValueError(
            f"Master admin password must be at least {min_length} characters long."
        )
    # Capture the previous hash so a ``save()`` failure (disk full, RO mount)
    # can revert the in-memory state — otherwise the process would accept the
    # new password while a restart loads the OLD one from disk.
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
    # Audit trail at INFO so operators can correlate a change with an incident.
    _logger.info("Master admin password updated")
    return True


@check_db_management_enabled
def exp_migrate_databases(databases: list[str]) -> Literal[True]:
    """Run ``base`` module upgrade against each listed database.

    Used by the HTTP database-manager "Migrate" action to bring several
    databases forward one Odoo version at a time.
    """
    # Reject the whole call if ANY target is unexposed, before migrating any,
    # so a mixed list can't leave a half-migrated result.
    for db in databases:
        check_db_exposed(db)
    for db in databases:
        _logger.info("migrate database %s", db)
        odoo.modules.registry.Registry.new(
            db, update_module=True, upgrade_modules={"base"}
        )
    return True


# ----------------------------------------------------------
# No master password required
# ----------------------------------------------------------


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
        # Definitely doesn't exist — clean negative answer, no diagnostic noise.
        _logger.debug("exp_db_exist(%r): database does not exist", db_name)
        return False
    except Exception:
        # Could be transient (pool saturation, PG restart, network).  Log at INFO
        # so the cause is visible without DEBUG; the ``mute_logger`` decorator
        # suppresses the duplicate line from the lower-level failure.
        _logger.info(
            "exp_db_exist(%r) returning False after non-existence error; "
            "may be transient (pool saturation, PG restart)",
            db_name,
            exc_info=True,
        )
        return False


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
        # No --db-filter but --database set: use it as the exposed-DB list
        # instead of querying the server (see the docstring).
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

    :param databases: A list of existing Postgresql databases
    :return: A list of databases that are incompatible
    """
    incompatible_databases = []
    server_version = ".".join(str(v) for v in version_info[:2])
    for database_name in databases:
        # Isolate each database: one unreachable / permission-denied DB must not
        # abort the whole scan.  Treat a DB we can't probe as incompatible so it
        # surfaces for attention.
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
                        # e.g. 10.saas~15
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
        finally:
            # Release the pool ``db_connect`` registered for EVERY probed DB, not
            # only the incompatible ones (else the common all-compatible case
            # leaks one idle pool per database).
            odoo.db.close_db(database_name)
    return incompatible_databases


def exp_list(document: bool = False) -> list[str]:
    """RPC entry point for ``list_dbs``. Raises ``AccessDenied`` if ``list_db`` is off.

    ``document`` is kept for backward compatibility with older XML-RPC clients
    but has no effect.
    """
    # ``list_dbs()`` enforces the ``list_db`` gate itself; no pre-check here.
    return list_dbs()


def exp_list_lang() -> list:
    """Return ``(code, name)`` pairs for every installable language."""
    return odoo.tools.misc.scan_languages()


def exp_list_countries() -> list[list[str]]:
    """Return ``[code, name]`` pairs for every country shipped in ``res.country`` XML.

    Reads the bundled XML directly rather than querying a database so it
    works before any DB exists (the DB-creation wizard needs this list
    on the pre-database selector page).
    """
    list_countries = []
    # Bundled read-only data file at a fixed path, not user input — defusedxml
    # unnecessary (replacing it already requires write to the install dir).
    root = ET.parse(  # noqa: S314
        Path(odoo.tools.config.root_path, "addons/base/data/res_country_data.xml")
    ).getroot()
    # Records may sit directly under <odoo> (current layout) or inside a legacy
    # <data> wrapper; match res.country records at any depth either way.
    for country in root.findall('.//record[@model="res.country"]'):
        name = country.find('field[@name="name"]').text
        code = country.find('field[@name="code"]').text
        list_countries.append([code, name])
    return sorted(list_countries, key=lambda c: c[1])


def exp_server_version() -> str:
    """Return the version of the server
    Used by the client to verify the compatibility with its own version
    """
    return odoo.release.version


# ----------------------------------------------------------
# db service dispatch
# ----------------------------------------------------------


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
        # Validate before unpacking so empty params raise ``TypeError`` (uniform
        # with the other dispatchers) rather than a ``ValueError`` from the unpack.
        if not params:
            raise TypeError(
                f"{method} requires a master password as its first positional "
                f"argument; got 0 arguments."
            )
        passwd, *params = params
        check_super(passwd)
    return handler(*params)


# Single allowlist for every db-service RPC method; master-password requirement
# is declared as data in ``_REQUIRES_MASTER_PASSWORD`` below, so the handlers
# stay plain functions that tests and internal callers can invoke directly.
_DISPATCH: dict[str, Callable] = {
    "db_exist": exp_db_exist,
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

# Methods whose first positional RPC param is the master password.  ``frozenset``
# for O(1), immutable membership.  Every entry MUST also exist in ``_DISPATCH``;
# ``TestDbDispatchAuth`` pins this.
#
# ``list_countries`` is intentionally absent: the unauthenticated DB-creation
# wizard calls it (reading bundled XML) before any DB exists, so it must stay
# public — also pinned by ``TestDbDispatchAuth``.
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
