"""A database's DDL lifecycle: create, drop, duplicate, rename — and the retries they need.

One of the five modules ``service/db.py`` was split into; the package
``__init__`` carries the shape and the dependency direction.
"""

import logging
import os
import shutil
import time
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import psycopg

import odoo.api
import odoo.db
import odoo.modules.db
import odoo.modules.neutralize
import odoo.tools
from odoo.tools import SQL

from .._db_helpers import (
    DatabaseExists,
    _drop_conn,
    check_db_management_enabled,
    database_identifier,
    validate_db_name,
)
from .listing import check_db_exposed

if TYPE_CHECKING:
    from odoo.db import BaseCursor
else:
    BaseCursor = Any

# The log channel stays "odoo.service.db" across the split: operators and
# log-reading tests key on it, and _db_helpers / _dump_scanner already spell
# it literally for the same reason.
_logger = logging.getLogger("odoo.service.db")


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
            except (
                psycopg.errors.DuplicateDatabase,
                psycopg.errors.UniqueViolation,
            ) as exc:
                raise DatabaseExists(f"database {db_name!r} already exists!") from exc

        _retry_terminate_then_ddl(
            cr,
            db_original_name,
            f"DUPLICATE DB: {db_original_name} -> {db_name}",
            _create_from_template,
        )

    try:
        registry = odoo.modules.registry.Registry.new(db_name, run_tests=False)
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
    odoo.modules.registry.Registry.forget(db_name)
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

    odoo.modules.registry.Registry.forget(old_name)
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
            except (
                psycopg.errors.DuplicateDatabase,
                psycopg.errors.UniqueViolation,
            ) as exc:
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
