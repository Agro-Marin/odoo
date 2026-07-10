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

# Helpers moved to a sibling module so this file stays focused on RPC
# entry points.  Re-exported below for backward compatibility — every
# external caller (cli/, addons/web/, tests) imports them from here.
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
    # PEP 649 lazy annotation evaluation introspects public function
    # signatures at runtime; ``BaseCursor`` from ``odoo.db`` would cycle
    # through ``odoo`` import bootstrap, so fall back to ``Any`` for the
    # runtime symbol while keeping the precise type for static analysis.
    BaseCursor = Any

_logger = logging.getLogger(__name__)

# Re-export under the public name so callers that do
# ``from odoo.service.db import DBNAME_PATTERN`` keep working.  The actual
# definitions live in ``_db_helpers``; listing them here makes the public
# surface explicit (and lets static-analysis tools see what's exported).
__all__ = (
    "DBNAME_MAX_LENGTH",
    "DBNAME_PATTERN",
    "DatabaseExists",
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

    Gated on BOTH the ``ODOO_FAKETIME_TEST_MODE`` env var AND the server
    running with ``test_enable``. Either gate alone is insufficient:

    * env-var-only means an accidental export in a systemd unit would silently
      corrupt every subsequent timestamp in production.
    * ``test_enable``-only would fire during every test run, even when no
      faketime shift is requested.

    Both must be true, and only for databases explicitly named in ``db_name``.
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
    # ``config['db_name']`` can legitimately be falsy (None or empty list) when
    # ``--database`` was not passed; ``cron_database_list`` for example treats
    # that case as "all databases".  Guard membership before the ``in`` check
    # to avoid ``TypeError: argument of type 'NoneType' is not iterable``.
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

    Lets PostgreSQL be the source of truth for existence: a pre-flight
    ``SELECT datname ...`` is racy — two concurrent creators can both see
    "does not exist" and one gets a raw ``DuplicateDatabase`` from PG.
    Instead, attempt ``CREATE DATABASE`` directly and translate PG's
    ``42P04`` error into the canonical ``DatabaseExists``.
    """
    db = odoo.db.db_connect("postgres")
    with closing(db.cursor()) as cr:
        chosen_template = odoo.tools.config["db_template"]
        # database-altering operations cannot be executed inside a transaction
        cr.rollback()
        cr.connection.autocommit = True

        # 'C' collate is only safe with template0 but provides more useful
        # indexes; skip it on any other template.  Two explicit code paths
        # are clearer (and harder to break) than one parameterised template
        # whose validity hinges on a trailing space inside an SQL fragment.
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
            # log_exceptions=False: DuplicateDatabase is an expected outcome on
            # the auto-create path used by ``cli/server.py`` (it calls this
            # function unconditionally and silently catches DatabaseExists).
            # Letting the cursor log its default ERROR for that case poisons
            # the test log with a misleading "bad query" line on every run
            # against a pre-existing DB.
            cr.execute(create_sql, log_exceptions=False)
        except psycopg.errors.DuplicateDatabase:
            already_exists = True

    # Create the PG extensions Odoo relies on, on BOTH the freshly-created
    # and the already-existed paths.  ``CREATE EXTENSION IF NOT EXISTS`` is
    # idempotent, and a pre-created DB (e.g. via ``createdb`` CLI before
    # ``odoo-bin`` started) will not have ``pg_trgm``/``unaccent`` unless
    # we install them here — without these, ``has_trigram()`` returns
    # False, ``Char.condition_to_sql`` skips the trigram-index prefilter,
    # and trigram-indexed translation searches silently lose their index
    # coverage (caught by ``test_orm.test_search_ilike``).  Failure here
    # means search features will silently degrade — escalate to ERROR and
    # mention the likely cause (missing contrib package, insufficient DB
    # privileges) so operators can act.
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

    # PG 15+ revoked CREATE on public schema by default; restore it for Odoo.
    # Idempotent and runs on the already-existed path too — a DB pre-created
    # via ``createdb`` CLI inherits PG's default-revoked GRANT, and Odoo
    # would later fail to create its own functions/types in public.
    try:
        db = odoo.db.db_connect(name)
        with db.cursor() as cr:
            cr.execute("GRANT CREATE ON SCHEMA PUBLIC TO PUBLIC")
    except psycopg.Error as e:
        _logger.warning("Unable to make public schema public-accessible: %s", e)

    if already_exists:
        # Signal "already exists" to the caller (which decides whether to
        # drop & recreate or reuse as-is — see ``cli/server.py:101``).
        # Done LAST so all idempotent setup (extensions, faketime, GRANT)
        # has run on the existing DB before the caller reuses it.
        raise DatabaseExists(f"database {name!r} already exists!")


def _rollback_new_database(db_name: str, what: str) -> None:
    """Drop a half-built database after a create/restore/duplicate failure.

    Call from the ``except`` of the population step, then re-``raise``.  All
    three paths create an empty (or template-copied) database and then populate
    it; on any failure the half-built database must be dropped so its name is
    reusable.  Uses the internal ``_drop_database`` (NOT ``exp_drop``, which
    re-checks the ``list_db`` flag — a runtime toggle between the initial check
    and this cleanup would orphan the database).  Drop failures are suppressed
    so they cannot mask the original error.  ``what`` is an operator-facing tag
    (``"CREATE DB"`` / ``"RESTORE DB"`` / ``"DUPLICATE DB"``).
    """
    _logger.info("%s: rolling back database %r after failure", what, db_name)
    with suppress(Exception):
        _drop_database(db_name)


def _assert_filestore_dest_free(dest: str, problem: str) -> None:
    """Pre-flight a name-creating op: refuse if its destination filestore exists.

    A leftover ``filestore/<name>/`` (from a failed drop, a manual ``dropdb``, or
    a crashed restore) would silently bind the new database to foreign
    attachments.  Run before any DB-level work so a conflict leaves nothing to
    roll back.  ``problem`` is the operation-specific lead; the shared remedy is
    appended.
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

    Rolls back the empty database on init failure (module install error,
    missing language, etc.) so the name can be reused for another attempt.
    Without this, ``initialize_db`` raising would leave a perfectly valid
    PG database with no Odoo schema — the operator would have to drop it
    by hand before retrying, mirroring the same bookkeeping ``restore_db``
    has had for years.
    """
    validate_db_name(db_name)
    # Pre-flight the destination filestore, exactly as duplicate/restore/rename
    # do: a leftover ``filestore/<name>/`` (failed drop, manual ``dropdb``,
    # crashed restore) would otherwise silently bind the fresh database to
    # foreign attachments.  Create was the only name-creating op missing this.
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
    """Duplicate ``db_original_name`` to ``db_name`` as a new database.

    Uses PostgreSQL's ``CREATE DATABASE ... TEMPLATE ...`` which requires the
    source to have no active connections — hence the ``close_db`` +
    ``_drop_conn`` preamble.

    Forces a new dbuuid (via ``ir.config_parameter.init(force=True)``) so the
    duplicate can coexist with the original in multi-DB deployments. When
    ``neutralize_database=True``, sensitive settings (SMTP, outgoing webhook
    URLs, etc.) are also scrubbed.

    On any failure after the new database is created (registry init, dbuuid
    write, neutralize, filestore copy) the empty database is dropped so the
    name is freed for another attempt.  Without this rollback, a failed copy
    leaves a perfectly valid PG database whose ``ir.attachment`` rows point
    at a filestore that was never created — a silent data-inconsistency that
    is easier to fix at create-time than after a user notices missing files.
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

        # ``CREATE DATABASE … TEMPLATE …`` requires zero sessions on the
        # source.  ``_drop_conn`` is best-effort (silent on missing
        # ``pg_signal_backend`` privilege), and a fresh request landing
        # between the terminate and the CREATE causes ``ObjectInUse``.
        # Retry with the same exponential backoff as ``_drop_database``;
        # this race is exactly the one the drop path was hardened against
        # and duplicate was overlooked.
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
                # Same exception type whether the name collision happens at
                # ``_create_empty_database`` or here.  (``ObjectInUse`` and any
                # other error propagate to the retry helper / caller.)
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
            # Race-safe re-check: ``to_fs`` may have appeared between the
            # pre-flight and now.  ``shutil.copytree`` raises ``FileExistsError``
            # if ``to_fs`` exists, but we surface a clearer message and let
            # the outer rollback drop the empty database.
            if Path(to_fs).exists():
                raise RuntimeError(
                    f"Filestore {to_fs!r} appeared between pre-flight and copy (race)."
                )
            shutil.copytree(from_fs, to_fs)
    except Exception:
        _rollback_new_database(db_name, "DUPLICATE DB")
        raise
    return True


# Max attempts for DROP DATABASE retry loop. A new HTTP request or cron tick
# can open a connection to the target DB in the window between
# ``pg_terminate_backend`` and ``DROP DATABASE``; retry several times with
# exponential backoff before surfacing the error to the operator.
#
# The cumulative budget across 5 attempts (0.2 + 0.4 + 0.8 + 1.6 + 3.2 = 6.2s)
# spans the realistic worst-case for a busy production DB: a connection
# holder needs to receive ``pg_terminate_backend``, unwind its transaction,
# commit/rollback, and fully release the connection.
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

    ``CREATE … TEMPLATE``, ``DROP DATABASE`` and ``ALTER DATABASE … RENAME`` all
    require zero sessions on the source/target.  ``_drop_conn`` evicts them
    best-effort, but a fresh request can connect in the window between the
    terminate and the DDL, so PostgreSQL raises ``ObjectInUse`` (sqlstate
    55006).  Each attempt re-terminates and re-runs ``run`` with the shared
    exponential backoff (0.2, 0.4, 0.8, 1.6, 3.2s).

    ``run`` executes the DDL and returns on success.  It MUST let
    ``ObjectInUse`` propagate (so this loop can retry) and may raise any other
    exception — ``DatabaseExists`` for a name collision, ``RuntimeError`` for an
    operation-specific failure — to abort immediately.  After
    ``_DROP_DATABASE_MAX_RETRIES`` exhausted attempts the last ``ObjectInUse``
    is re-raised wrapped in ``RuntimeError``.
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
            # Don't sleep after the final attempt — the loop is about to exit
            # and raise, so the backoff would only delay the error by its
            # longest interval (3.2s) for no retry.
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

    Single source of truth shared by every dump path — the blocking
    ``subprocess.run`` calls (zip format, and non-streaming custom format) and
    the streaming ``Popen`` copy.  Previously only the streaming path was
    bounded, so a hung ``pg_dump`` on the common web-backup path (zip,
    ``stream=None``) could block a worker indefinitely (PG-side lock wait, a
    remote PG that stops responding).  Default 1h is generous for legitimate
    big-DB dumps but finite; override via ``ODOO_PG_DUMP_TOTAL_TIMEOUT``.
    A malformed value falls back to the default rather than crashing the dump.
    """
    return env_float("ODOO_PG_DUMP_TOTAL_TIMEOUT", 3600.0, logger=_logger)


def _pg_restore_total_timeout() -> float:
    """Wall-clock ceiling (seconds) for the ``psql``/``pg_restore`` invocation.

    Sibling of ``_pg_dump_total_timeout``.  The restore subprocess was the
    asymmetric gap: the dump path bounds every ``pg_dump`` call, but a hung
    ``psql -f`` (PG-side lock wait, disk-full stall, a dump that triggers a
    slow trigger) would block the worker until the master watchdog SIGKILLs
    it — a cruder backstop than the clean ``RuntimeError`` the dump path
    raises.  Default 1h; override via ``ODOO_PG_RESTORE_TOTAL_TIMEOUT``.  A
    malformed value falls back to the default rather than crashing the restore.
    """
    return env_float("ODOO_PG_RESTORE_TOTAL_TIMEOUT", 3600.0, logger=_logger)


def _drop_database(db_name: str) -> bool:
    """Internal DROP DATABASE helper, used by both ``exp_drop`` and cleanup paths.

    Not decorated with ``@check_db_management_enabled``: cleanup-on-failure
    callers (e.g. ``restore_db`` rolling back an empty database) must not
    be blocked by a runtime toggle of ``list_db``.

    Handles the terminate-then-drop race: another thread (cron, HTTP) can
    open a new connection between ``pg_terminate_backend`` and ``DROP
    DATABASE``. PostgreSQL signals this via ``ObjectInUse`` (sqlstate 55006).
    Retry up to ``_DROP_DATABASE_MAX_RETRIES`` times, re-running the
    terminate step each iteration.
    """
    # Existence check against PostgreSQL itself, NOT ``list_dbs(True)``: when
    # ``--database`` is set without ``--db-filter``, ``list_dbs(True)`` returns
    # the configured allowlist, so a freshly-created database outside that list
    # (e.g. a half-built one being rolled back after a failed
    # create/restore/duplicate) would wrongly look non-existent and this drop
    # would silently no-op, orphaning it.  The pg_database probe uses an
    # autocommit cursor on the maintenance DB so it never blocks on the target
    # database's transaction state.
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
        # If we cannot probe (e.g. no access to the maintenance DB), fall
        # through and let DROP DATABASE below surface the real error rather
        # than silently returning False.
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

    # Close pools again: between close_db() above and the actual DROP,
    # other threads (cron, HTTP) may have re-created a pool for this
    # database.  Clean them up so they don't try to reconnect to a
    # database that no longer exists.
    odoo.db.close_db(db_name)

    fs = odoo.tools.config.filestore(db_name)
    if Path(fs).exists():
        shutil.rmtree(fs)
    return True


@check_db_management_enabled
def exp_drop(db_name: str) -> bool:
    """Drop a database (public/RPC-facing, subject to ``list_db`` gate)."""
    return _drop_database(db_name)


@check_db_management_enabled
def exp_dump(db_name: str, backup_format: str) -> str:
    """Dump the database and return its base64-encoded content.

    Encodes in 3 MiB chunks against an on-disk tempfile, so the raw N bytes
    never sit in memory.  Peak memory is ``~8N/3``: the ``bytearray``
    accumulator (``4N/3``) is briefly co-resident with the final ``str``
    (``4N/3``) during ``decode("ascii")`` (measured 2.68x input at N=30 MiB).
    A multi-GB dump still doubles process RSS — callers that need true
    streaming should use ``dump_db(..., stream=...)`` with a writable file
    or response object.

    The web UI at ``/web/database/backup`` does NOT go through this function:
    it calls ``dump_db(name, None, ...)`` (``stream=None``), which buffers the
    dump to a ``TemporaryFile`` and hands that file object to werkzeug's
    ``Response(..., direct_passthrough=True)`` — so the base64 round-trip here
    is avoided, but the dump is still fully written to a temp file first.  The
    only true-streaming caller is the ``odoo db dump`` CLI (``stream`` = a real
    file / ``sys.stdout.buffer``).
    """
    # 3 MiB — a multiple of 3 so each chunk encodes independently (base64
    # consumes 3 input bytes per 4 output chars; non-3-aligned chunks would
    # emit padding mid-stream).
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

    Shared by the two blocking dump paths: the zip path (``stdout`` =
    ``DEVNULL``; the dump is written via an inserted ``--file=``) and the
    buffered custom-format path (``stdout`` = a ``TemporaryFile``).  Bounds the
    run with ``_pg_dump_total_timeout`` so a hung pg_dump cannot block a worker
    indefinitely — ``subprocess.run`` kills and reaps the child on timeout.
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


# Grace (seconds) between the stall timer's SIGTERM and its follow-up SIGKILL
# in ``_run_pg_dump_streaming``.  A backstop for a pg_dump that ignores SIGTERM,
# not a user-tuning surface — kept small and fixed so a wedged dump can't hold a
# worker much past the total timeout.
_STALL_SIGKILL_GRACE_S = 10.0


def _run_pg_dump_streaming(cmd: list[str], env: dict, stream: IO[bytes]) -> None:
    """Stream a custom-format ``pg_dump`` to ``stream`` while draining stderr.

    stdout is copied to ``stream`` as it is produced; a sibling thread drains
    stderr concurrently so neither pipe blocks when pg_dump emits more than the
    OS pipe buffer (64 KiB default) of warnings — a model-rich DB clears that
    cap routinely.  A wall-clock ``Timer`` SIGTERMs a stalled pg_dump, because
    ``copyfileobj`` is otherwise unbounded if stdout EOF never arrives (PG-side
    lock wait, a remote PG that stops responding).  After the copy, a bounded
    post-EOF wait escalates SIGTERM → SIGKILL.  Raises ``RuntimeError`` on
    stall or non-zero exit.
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
        # Escalate to SIGKILL if SIGTERM does not unblock the copy.  The
        # SIGTERM -> wait -> SIGKILL ladder in the ``finally`` below only runs
        # AFTER ``copyfileobj`` returns — i.e. only after stdout EOFs.  But a
        # pg_dump wedged uninterruptibly (or ignoring SIGTERM) never EOFs
        # stdout, so ``copyfileobj`` would block forever and that ladder would
        # never run, degrading the documented hard wall-clock ceiling to a
        # single best-effort signal.  Forcing SIGKILL here (from the Timer
        # thread) makes stdout EOF, unblocking the copy so the ``finally`` can
        # reap.  Concurrent ``proc.wait`` from the copy thread's ``finally`` is
        # safe — CPython serialises waits and caches the returncode.  This makes
        # the streaming path match the blocking path's ``subprocess.run(
        # timeout=...)`` kill-and-reap guarantee.
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
        # Bounded post-EOF wait + escalating signals.  Operator-friendly
        # default 30s; override via env.  Parsed through ``env_float`` so a
        # malformed value falls back to the default instead of raising
        # ``ValueError`` from this ``finally`` — which would crash a successful
        # dump and mask the real error of a failed one.
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
        # race — pg_dump can reach stdout EOF (returncode 0) at the same instant
        # the timer fires and sets ``stall_killed``.  A genuine stall kill leaves
        # a signal returncode (negative), so gating on a non-zero exit keeps a
        # successful dump from being reported as a spurious timeout.
        # Typed error so callers can distinguish "stalled" from "non-zero exit".
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
        For the ``zip`` format this is a **best-effort online snapshot**, not
        a transactional one.  The manifest is written first (it opens a cursor
        on the source DB, so it doubles as a cheap connectivity/existence check
        and an unreachable DB fails before the filestore copy), then the
        filestore is copied (line-of-fire ``shutil.copytree``), then ``pg_dump``
        runs as a separate process.  Concurrent writes during the
        copytree→pg_dump window produce inconsistent dumps:

        * a new ``ir.attachment`` row whose binary was written to the filestore
          AFTER the copytree but BEFORE pg_dump → row in dump.sql, file missing.
        * a row deleted between the two → file present in the dump's filestore
          but no row pointing at it.

        For backup-of-record on a busy production DB, freeze writes externally
        (read-only mode, application pause) before invoking, or use
        physical-replica snapshots.
    """
    # Enforce the same name shape/length guarantee as create/duplicate/rename/
    # restore.  ``dump_db`` was the last name-accepting entry point that fed
    # ``db_name`` straight into the ``pg_dump`` argv (and, for the zip format,
    # into ``db_connect``) without validation.  Because the name is a *trailing*
    # positional arg, an unvalidated value like ``--jobs=…`` or ``--version``
    # is parsed by pg_dump as an option rather than a database (argument
    # injection — no shell, so not RCE).  The custom-format path has no
    # ``db_connect`` ahead of it to reject the name first, so the guard belongs
    # here, before any argv is built.
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
            # Manifest first: ``db_connect`` + cursor here is the cheapest
            # operation that touches the source DB, so writing the manifest
            # before the (potentially multi-GB) filestore copytree makes an
            # unreachable or bogus DB fail fast instead of after the copy.  It
            # does not widen the consistency window, which is copytree→pg_dump.
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
                    # Close on any abnormal exit (zip_dir error, OSError
                    # mid-write) so the OS fd is not leaked until GC.
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

    ``data`` is the base64 body of a zip (v8+ format) or raw pg_dump custom
    format.  Whitespace inside ``data`` is tolerated: PEM/MIME-style line
    breaks (``\\n`` every 76 chars) used to crash chunked decoding with
    ``binascii.Error: Incorrect padding`` because chunk boundaries landed
    mid-group on the 76-char wrap.  The accumulator below buffers
    un-decoded chars across chunks so every ``b64decode`` call gets a
    multiple of 4 chars, and ASCII whitespace is stripped per-chunk.

    ``copy=True`` forces a new dbuuid so the restored DB can coexist with
    the original.
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
        # Close before unlinking: on the decode-error path (malformed base64
        # from an RPC client) the ``data_file.close()`` above is skipped, so the
        # fd would leak until GC.  ``close()`` is idempotent, so calling it again
        # on the success path is harmless.
        data_file.close()
        # ``missing_ok`` so a racing deletion (e.g. tmp cleaner, concurrent
        # admin action) cannot replace a successful restore with a spurious
        # FileNotFoundError from the finally block.
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

    Handles both the v8+ zip format (SQL + filestore + manifest) and the
    raw pg_dump custom format for pre-v8 dumps. On any failure after the
    empty database is created, ``_drop_database`` is called to release the
    name for another restore attempt.

    ``copy=True`` forces a new dbuuid. ``neutralize_database=True`` also
    scrubs external-integration config (SMTP, webhooks, etc.) for use on
    staging/testing clones.

    Pre-flights the destination filestore.  ``shutil.move(src, dst)`` where
    ``dst`` is an existing directory silently produces ``dst/<src_basename>/``
    instead of replacing ``dst`` — a leftover ``filestore/<db>/`` (orphaned
    by an earlier failed drop, manual ``dropdb``, or crashed restore) would
    otherwise nest the dumped filestore inside the stale one, leaving
    ``ir.attachment`` rows resolving against the wrong tree.
    """
    if not isinstance(db, str):
        raise TypeError(f"db must be a str, got {type(db).__name__!r}")
    # Validate name shape/length (else PG silently truncates a 64+ char name
    # to 63 bytes), same gate as create/duplicate/rename.
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
                    # Belt-and-suspenders ZipSlip defense: Python 3.6+ strips
                    # ``..`` components from extractall paths, but an explicit
                    # check pinned to THIS file holds even if a future
                    # maintainer switches to ``z.extract(...)`` or another
                    # library.  Validate member names BEFORE extraction so
                    # the cost is O(zip-entries) instead of O(extracted-files)
                    # — a backup with 50k attachments would otherwise pay 50k
                    # ``Path.resolve()`` syscalls on the restore hot path.
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
                # ``-v ON_ERROR_STOP=1`` is REQUIRED: ``psql -f`` otherwise
                # exits 0 even when individual SQL statements fail, so a
                # truncated/version-mismatched/disk-full dump would restore a
                # partially-populated database and the ``r.returncode != 0``
                # guard below would never trip — a silent partial restore
                # reported as success.  With the flag psql exits non-zero on
                # the first ERROR, which propagates to the rollback path.
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
                # ``--exit-on-error`` for the same reason the zip path passes
                # ``psql -v ON_ERROR_STOP=1``: pg_restore's DEFAULT is to
                # CONTINUE past per-statement errors and still exit 0, which
                # would restore a partially-populated database that the
                # ``r.returncode != 0`` guard below never catches — a silent
                # partial restore reported as success.  The target is a fresh
                # empty DB (``_create_empty_database`` above), so a clean dump
                # produces no errors and this only bites a genuinely broken one.
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
                # ``subprocess.run`` has already killed and reaped the child.
                # The ``except`` below drops the half-restored database so the
                # name is released for another attempt.
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
                    # between the pre-flight and now.  ``shutil.move(src, dst)``
                    # with ``dst`` as an existing directory moves ``src`` *into*
                    # ``dst``, producing ``dst/<src_basename>`` — silent
                    # corruption that would survive every later check.
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
    """Rename a database.

    Validates the new name against ``DBNAME_PATTERN`` (same gate as create),
    tears down the old registry and connection pool, issues ``ALTER
    DATABASE RENAME`` in autocommit (with the same exponential-backoff
    retry on ``ObjectInUse`` as ``_drop_database`` and
    ``exp_duplicate_database``), then renames the filestore directory.
    No new registry is eagerly built — the next request to ``new_name``
    lazy-loads it, matching ``exp_create_database`` behavior.

    Refuses pre-flight when the destination filestore already exists.  A
    leftover ``filestore/<new_name>/`` (orphaned by an earlier failed drop,
    a manual ``dropdb``, or a crashed restore) would silently bind the
    renamed database to a foreign filestore, serving wrong attachments.
    Operators must move or delete the stale directory before retrying.

    If ``shutil.move`` fails after the SQL rename succeeded, the database is
    renamed back to ``old_name`` so DB and filestore stay in sync — the
    half-done state ("DB at new_name, filestore at old_name") would silently
    serve attachments to the wrong database after a future rename.  If the
    rename-back itself fails, the original error is raised wrapped with both
    failures so operators can intervene manually.
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

        # Same terminate-then-act race as DROP / DUPLICATE: a fresh request
        # can land between ``_drop_conn`` and ``ALTER DATABASE … RENAME``.
        # Retry with the shared exponential backoff so RENAME degrades
        # gracefully under load instead of one-shot failing where the other
        # two operations recover.
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
                # Same exception type whether the collision happens at
                # create / duplicate / rename time.
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
            # Race-safe re-check: ``new_fs`` may have appeared between the
            # pre-flight and now.  ``shutil.move(src, dst)`` with ``dst`` as
            # an existing directory moves ``src`` *into* ``dst``, producing
            # ``dst/src_basename`` instead of replacing ``dst`` — silent
            # corruption that would survive the post-condition checks.
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

    Extracted so the rollback path is identical for both filestore-move
    failures and the race-window case (``new_fs`` appeared between the
    pre-flight check and the move).
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

    Enforces a minimum length — the master password authorises every
    database-level destructive operation (drop, rename, restore) so it
    is the highest-value credential in the instance.  Default minimum
    is 8 characters; override via ``ODOO_ADMIN_PASSWORD_MIN_LENGTH`` for
    deployments under stricter regimes (NIST SP 800-63B → 12+, ISO 27001,
    etc.).  Compliance owners can raise the floor without code changes.

    Additional complexity checks (character classes, dictionary
    prohibition, etc.) belong in the HTTP controller when the policy
    needs to stay configurable per deployment.
    """
    if not isinstance(new_password, str):
        raise TypeError(
            f"new_password must be a str, got {type(new_password).__name__!r}"
        )
    # Silent (no ``logger``): this credential path deliberately keeps quiet.
    # ``minimum=8`` is the hard floor — the env var can only RAISE it (stricter
    # regimes), never weaken it; a malformed value falls back to 8.
    min_length = env_int("ODOO_ADMIN_PASSWORD_MIN_LENGTH", 8, minimum=8)
    if len(new_password) < min_length:
        raise ValueError(
            f"Master admin password must be at least {min_length} characters long."
        )
    # Atomic update: capture the previous hash before mutating so a save()
    # failure can revert in-memory state.  Without this, ``set_admin_password``
    # would update ``self.options`` to the new hash and ``save`` could still
    # raise (disk full, EPERM, mount RO) — leaving the running process
    # accepting the new password while a restart loaded the OLD one from disk.
    # That divergence is silent and only surfaces after the next restart.
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
    # Audit trail: the master password authorises every destructive op
    # (drop, rename, restore).  Pin successful changes at INFO so operators
    # can correlate with the security incident timeline.
    _logger.info("Master admin password updated")
    return True


@check_db_management_enabled
def exp_migrate_databases(databases: list[str]) -> Literal[True]:
    """Run ``base`` module upgrade against each listed database.

    Used by the HTTP database-manager "Migrate" action to bring several
    databases forward one Odoo version at a time.
    """
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

    This is weaker than "the database exists": a database that exists but
    is inaccessible (permission denied, pool saturated, etc.) returns False.
    For the database-manager wizard and XML-RPC callers, the weaker check
    is the right semantic — they care whether Odoo can actually use it.

    The False return is intentionally undifferentiated for the public
    contract, but the underlying failure mode is logged at DEBUG level so
    operators investigating "why does my UI say the DB doesn't exist?" can
    distinguish "really doesn't exist" (psycopg ``InvalidCatalogName``,
    SQLSTATE 3D000) from "transient PG issue" (semaphore saturation, pool
    timeout, network blip).
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
        # Could be transient (pool saturation, PG restart, network).  Log at
        # INFO so the cause is visible without forcing operators to enable
        # DEBUG; ``mute_logger("odoo.db")`` decorator suppresses the duplicate
        # log line from the lower-level connection failure.
        _logger.info(
            "exp_db_exist(%r) returning False after non-existence error; "
            "may be transient (pool saturation, PG restart)",
            db_name,
            exc_info=True,
        )
        return False


def list_dbs(force: bool = False) -> list[str]:
    """List databases visible to this Odoo instance.

    Priority order:
    1. Fail with ``AccessDenied`` unless ``list_db=True`` or ``force=True``.
    2. If ``--dbfilter`` is unset and ``-d/--database`` is set, return the
       configured list as-is (explicit allowlist, PG roundtrip skipped).
    3. Otherwise, query ``pg_database`` filtered to DBs owned by the
       current PG role (``datdba = usesysid of current_user``) — this is
       how shared PG-server setups keep instances from enumerating each
       other. If two Odoo instances share a PG role, they'll see each
       other's DBs; give each instance its own role for isolation.

    The system database (``postgres``) and the configured template are
    excluded so they never appear in the manager UI.
    """
    if not odoo.tools.config["list_db"] and not force:
        raise odoo.exceptions.AccessDenied

    if not odoo.tools.config["dbfilter"] and odoo.tools.config["db_name"]:
        # In case --db-filter is not provided and --database is passed, Odoo will not
        # fetch the list of databases available on the postgres server and instead will
        # use the value of --database as comma seperated list of exposed databases.
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
        # Isolate each database: a single unreachable / permission-denied DB
        # (the input often comes from ``list_dbs()``, which can include DBs this
        # role cannot open) must not abort the whole compatibility scan.  Treat a
        # DB we cannot probe as incompatible so it surfaces for attention.
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
            # Release the connection pool ``db_connect`` registered for EVERY
            # database probed, not only the incompatible ones — the previous code
            # closed pools solely for the incompatible set, leaking one idle pool
            # per compatible database (the common all-compatible case).
            odoo.db.close_db(database_name)
    return incompatible_databases


def exp_list(document: bool = False) -> list[str]:
    """RPC entry point for ``list_dbs``. Raises ``AccessDenied`` if ``list_db`` is off.

    The ``document`` parameter is kept for backward compatibility with older
    XML-RPC clients that send it; it has no effect — Odoo no longer ships a
    document-management module distinct from the regular DB list.
    """
    # ``list_dbs()`` enforces the ``list_db`` gate itself (raises AccessDenied
    # when the config flag is off and force=False).  No pre-check needed here.
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
    # Bundled read-only data file, not user input — defusedxml unnecessary.
    # The path is fixed under the install root; an attacker who could replace
    # this file already has filesystem write to the Odoo install dir.
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

    Single allowlist (``_DISPATCH``) for handler resolution; sister set
    (``_REQUIRES_MASTER_PASSWORD``) for auth declaration. The two-dict
    pattern that preceded this kept ``_DISPATCH_PUBLIC`` and
    ``_DISPATCH_ADMIN`` disjoint by convention — the convention was
    enforceable only by tests. With one dict, no key can be in both
    "public" and "admin" simultaneously: it's structurally impossible.

    Raises ``AttributeError`` for unknown methods — matching the exception type
    raised by ``odoo.service.common.dispatch`` and ``odoo.service.model.dispatch``
    so callers see uniform behavior across the three RPC services.

    TRUST BOUNDARY: the master-password check lives HERE, at the RPC edge — not
    on the ``exp_*`` handlers.  A direct in-process call (e.g. ``exp_drop`` from
    CLI/migration code) is considered trusted and bypasses the password, but is
    still gated by ``@check_db_management_enabled`` (the ``list_db`` flag) on
    the handler itself.  Keep destructive handlers decorated so that gate holds
    for internal callers too.
    """
    handler = _DISPATCH.get(method)
    if handler is None:
        raise AttributeError(f"Method not found: {method}")
    if method in _REQUIRES_MASTER_PASSWORD:
        # Validate before unpacking: a bare ``passwd, *params = params`` raises
        # ``ValueError: not enough values to unpack`` on empty input — different
        # from the ``TypeError`` that ``odoo.service.model.dispatch`` raises for
        # the same shape of malformed call. Surface a typed error consistent
        # with the other dispatchers so RPC clients see one error class for
        # "argument count wrong" everywhere.
        if not params:
            raise TypeError(
                f"{method} requires a master password as its first positional "
                f"argument; got 0 arguments."
            )
        passwd, *params = params
        check_super(passwd)
    return handler(*params)


# Single allowlist for every db-service RPC method.  Whether a method
# requires the master password is declared in ``_REQUIRES_MASTER_PASSWORD``
# below — auth is data, not a function decorator, so the underlying
# handlers stay plain functions that tests and internal callers can
# invoke without ceremony.
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

# Methods whose first positional RPC param is the master password.
# ``frozenset`` so the membership test in ``dispatch`` is O(1) and the
# set is immutable at module load (a future contributor can't mutate the
# auth gate from another module).  Every entry MUST also exist in
# ``_DISPATCH``; ``base/tests/test_server.py::TestDbDispatchAuth`` pins this
# invariant.
#
# ``list_countries`` is intentionally absent: it reads bundled XML
# (``addons/base/data/res_country_data.xml``) and is invoked by the
# unauthenticated database-creation wizard before any DB exists.  Gating
# it would either raise ``ValueError`` on the empty-params unpack or
# ``AccessDenied`` on a public read; ``TestDbDispatchAuth`` pins that it
# (and the other public reads) stay unauthenticated.
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
