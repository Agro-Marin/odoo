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
from .listing import check_db_exposed, invalidate_catalog_caches

if TYPE_CHECKING:
    from odoo.db import BaseCursor
else:
    BaseCursor = Any

_logger = logging.getLogger("odoo.service.db")


def _check_faketime_mode(db_name: str) -> None:
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

    invalidate_catalog_caches()

    if already_exists:
        raise DatabaseExists(f"database {name!r} already exists!")


def _rollback_new_database(db_name: str, what: str) -> None:
    _logger.info("%s: rolling back database %r after failure", what, db_name)
    with suppress(Exception):
        _drop_database(db_name)


def _assert_filestore_dest_free(dest: str, problem: str) -> None:
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
    invalidate_catalog_caches()
    return True


_DROP_DATABASE_MAX_RETRIES = 5


_DROP_DATABASE_BACKOFF_BASE = 0.2


def _retry_on_object_in_use(
    op_label: str,
    run: Callable[[], None],
    *,
    before_attempt: Callable[[], None] | None = None,
) -> None:
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
    _retry_on_object_in_use(
        op_label, run, before_attempt=lambda: _drop_conn(cr, terminate_target)
    )


def _drop_database(db_name: str) -> bool:
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
    invalidate_catalog_caches()
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
    invalidate_catalog_caches()
    return True


def _rollback_db_rename(cr: BaseCursor, old_name: str, new_name: str) -> None:
    cr.execute(
        SQL(
            "ALTER DATABASE %s RENAME TO %s",
            database_identifier(cr, new_name),
            database_identifier(cr, old_name),
        )
    )
