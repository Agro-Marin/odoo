import argparse
import functools
import getpass
import logging
import pathlib
import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import psycopg

from odoo.db import db_connect, get_connection_info_for_database
from odoo.tools import SQL

from . import DatabaseCommand

if TYPE_CHECKING:
    from odoo.db import Cursor

_logger = logging.getLogger(__name__)

DEFAULT_FIELDS: tuple[tuple[str, str], ...] = (
    ("mail_tracking_value", "old_value_char"),
    ("mail_tracking_value", "old_value_text"),
    ("mail_tracking_value", "new_value_char"),
    ("mail_tracking_value", "new_value_text"),
    ("res_partner", "name"),
    ("res_partner", "complete_name"),
    ("res_partner", "email"),
    ("res_partner", "phone"),
    ("res_partner", "mobile"),
    ("res_partner", "street"),
    ("res_partner", "street2"),
    ("res_partner", "city"),
    ("res_partner", "zip"),
    ("res_partner", "vat"),
    ("res_partner", "website"),
    ("res_country", "name"),
    ("mail_message", "subject"),
    ("mail_message", "email_from"),
    ("mail_message", "reply_to"),
    ("mail_message", "body"),
    ("crm_lead", "name"),
    ("crm_lead", "contact_name"),
    ("crm_lead", "partner_name"),
    ("crm_lead", "email_from"),
    ("crm_lead", "phone"),
    ("crm_lead", "mobile"),
    ("crm_lead", "website"),
    ("crm_lead", "description"),
)


def _parse_field_spec(spec: str) -> tuple[str, str]:
    parts = spec.strip().split(".")
    if len(parts) != 2 or not all(parts):
        msg = f"Invalid field specification {spec!r}: expected 'table.column'"
        raise ValueError(msg)
    return parts[0], parts[1]


def _get_fields_selected(opt: argparse.Namespace) -> list[tuple[str, str]]:
    fields = [] if opt.no_default_fields else list(DEFAULT_FIELDS)
    if opt.fields:
        if opt.allfields:
            _logger.warning("--allfields is set: ignoring --fields")
        else:
            fields += [_parse_field_spec(f) for f in opt.fields.split(",")]
    if opt.file:
        if opt.allfields:
            _logger.warning("--allfields is set: ignoring --file")
        else:
            fields += list(_read_field_file(opt.file))
    if opt.exclude:
        if opt.allfields:
            _logger.warning("--allfields is set: ignoring --exclude")
        else:
            excluded = {_parse_field_spec(e) for e in opt.exclude.split(",")}
            fields = [f for f in fields if f not in excluded]
    return fields


@functools.cache
def _read_field_file(path: str) -> tuple[tuple[str, str], ...]:
    with pathlib.Path(path).open(encoding="utf-8") as f:
        return tuple(_parse_field_spec(line) for line in f if line.strip())


class Obfuscate(DatabaseCommand):
    description = "Obfuscate data in a given odoo database"

    def __init__(self) -> None:
        super().__init__()
        self._cr: Cursor | None = None
        self.dbname: str = ""
        self._field_kinds: dict[tuple[str, str], str] | None = None
        self._field_widths: dict[tuple[str, str], int] | None = None
        self._add_arguments()

    @property
    def cr(self) -> Cursor:
        if self._cr is None:
            msg = "No database connection"
            raise RuntimeError(msg)
        return self._cr

    @cr.setter
    def cr(self, cr: Cursor | None) -> None:
        self._cr = cr

    def _get_row(self) -> tuple[Any, ...]:
        row = self.cr.fetchone()
        if row is None:
            msg = "query returned no row where one was guaranteed"
            raise RuntimeError(msg)
        return row

    def _install_cypher_support(self) -> None:
        self.cr.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        self.cr.execute(
            """
            CREATE OR REPLACE FUNCTION pg_temp.odoo_cyph_marked(value text, pwd text)
            RETURNS boolean LANGUAGE plpgsql AS $$
            BEGIN
                IF value IS NULL OR NOT starts_with(value, 'odoo_cyph_') THEN
                    RETURN false;
                END IF;
                PERFORM pgp_sym_decrypt(decode(substring(value from 11), 'base64'), pwd);
                RETURN true;
            EXCEPTION WHEN OTHERS THEN
                RETURN false;
            END;
            $$
            """
        )

    def commit(self) -> None:
        self.cr.commit()

    def rollback(self) -> None:
        self.cr.rollback()

    def _insert_password_marker(self, pwd: str) -> None:
        self.cr.execute(
            "INSERT INTO ir_config_parameter (key, value) VALUES ('odoo_cyph_pwd', 'odoo_cyph_'||encode(pgp_sym_encrypt(%s, %s), 'base64')) ON CONFLICT(key) DO NOTHING",
            [pwd, pwd],
        )

    def _is_password_valid(self, pwd: str) -> bool:
        uncypher_pwd = self._prepare_uncypher_sql(SQL.identifier("value"), pwd)

        try:
            query = SQL(
                "SELECT %s FROM ir_config_parameter WHERE key='odoo_cyph_pwd'",
                uncypher_pwd,
            )
            self.cr.execute(query)
            if self.cr.rowcount == 0 or (
                self.cr.rowcount == 1 and self._get_row()[0] == pwd
            ):
                return True
        except psycopg.errors.ExternalRoutineInvocationException as e:
            _logger.info("Password check failed: %s", e)
        return False

    def _remove_password_marker(self) -> None:
        self.cr.execute("DELETE FROM ir_config_parameter WHERE key='odoo_cyph_pwd'")

    def _prepare_cypher_sql(self, sql_field: SQL, password: str) -> SQL:
        return SQL(
            """CASE WHEN pg_temp.odoo_cyph_marked(%(field_name)s, %(pwd)s) THEN %(field_name)s ELSE 'odoo_cyph_'||encode(pgp_sym_encrypt(%(field_name)s, %(pwd)s), 'base64') END""",
            field_name=sql_field,
            pwd=password,
        )

    def _prepare_uncypher_sql(self, sql_field: SQL, password: str) -> SQL:
        return SQL(
            """CASE WHEN pg_temp.odoo_cyph_marked(%(field_name)s, %(pwd)s) THEN pgp_sym_decrypt(decode(substring(%(field_name)s, 11)::text, 'base64'), %(pwd)s) ELSE %(field_name)s END""",
            field_name=sql_field,
            pwd=password,
        )

    @staticmethod
    def _get_column_kind(udt_name: str) -> str | None:
        if udt_name in ("text", "varchar"):
            return "string"
        if udt_name == "jsonb":
            return "json"
        return None

    _CATALOG_COLUMNS = (
        "SELECT table_name, column_name, udt_name, character_maximum_length"
        " FROM information_schema.columns"
        " WHERE table_schema = current_schema"
        "   AND udt_name IN ('text', 'varchar', 'jsonb')"
    )

    def _index_field_catalog(self, rows: list[tuple]) -> None:
        self._field_kinds = {}
        self._field_widths = {}
        for table, column, udt, max_length in rows:
            if kind := self._get_column_kind(udt):
                self._field_kinds[table, column] = kind
                if max_length is not None:
                    self._field_widths[table, column] = max_length

    def _load_field_catalog(self, tables: set[str] | list[str]) -> None:
        self._field_kinds = {}
        self._field_widths = {}
        if not tables:
            return
        self.cr.execute(
            f"{self._CATALOG_COLUMNS} AND table_name = ANY(%s)",
            [list(tables)],
        )
        self._index_field_catalog(self.cr.fetchall())

    def _get_field_kind(self, table: str, field: str) -> str | None:
        if self._field_kinds is not None:
            return self._field_kinds.get((table, field))
        qry = "SELECT udt_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s AND table_schema = current_schema"
        self.cr.execute(qry, [table, field])
        if self.cr.rowcount == 1:
            return self._get_column_kind(self._get_row()[0])
        return None

    def _get_fields_unfittable(
        self, fields: list[tuple[str, str]], pwd: str
    ) -> list[tuple[tuple[str, str], int, int]]:
        unfittable = []
        for field in fields:
            width = (self._field_widths or {}).get(field)
            if width is None:
                continue
            table, column = field
            sql_field = SQL.identifier(column)
            self.cr.execute(
                SQL(
                    "SELECT length('odoo_cyph_' || encode(pgp_sym_encrypt("
                    "repeat('x', COALESCE(MAX(octet_length(%s)), 0)), %s"
                    "), 'base64')) FROM %s"
                    " WHERE %s IS NOT NULL AND NOT starts_with(%s, 'odoo_cyph_')",
                    sql_field,
                    pwd,
                    SQL.identifier(table),
                    sql_field,
                    sql_field,
                )
            )
            row = self.cr.fetchone()
            projected = row[0] if row and row[0] is not None else 0
            if projected > width:
                unfittable.append((field, width, projected))
        return unfittable

    def _get_fields_obfuscatable(self) -> list[tuple[str, str]]:
        self.cr.execute(
            f"{self._CATALOG_COLUMNS}"
            " AND NOT starts_with(table_name, 'ir_')"
            " ORDER BY 1, 2"
        )
        rows = self.cr.fetchall()
        self._index_field_catalog(rows)
        return [(table, column) for table, column, _udt, _len in rows]

    def _update_table_values(
        self,
        table: str,
        fields: set[str] | list[str],
        pwd: str,
        with_commit: bool = False,
        unobfuscate: bool = False,
    ) -> None:
        cypherings = []
        conditions = []
        cyph_fct = (
            self._prepare_uncypher_sql if unobfuscate else self._prepare_cypher_sql
        )

        for field in fields:
            field_type = self._get_field_kind(table, field)
            sql_field = SQL.identifier(field)
            if field_type == "string":
                cypher_query = cyph_fct(sql_field, pwd)
                cypherings.append(SQL("%s=%s", SQL.identifier(field), cypher_query))
                if unobfuscate:
                    conditions.append(
                        SQL("pg_temp.odoo_cyph_marked(%s, %s)", sql_field, pwd)
                    )
                else:
                    conditions.append(
                        SQL(
                            "(%s IS NOT NULL AND NOT pg_temp.odoo_cyph_marked(%s, %s))",
                            sql_field,
                            sql_field,
                            pwd,
                        )
                    )
            elif field_type == "json":
                new_field_value = sql_field
                for key in self._get_keys_in_jsonb_column(table, field):
                    cypher_query = cyph_fct(SQL("%s->>%s", sql_field, key), pwd)
                    new_field_value = SQL(
                        "CASE WHEN jsonb_typeof(%s->%s) = 'string' "
                        "THEN jsonb_set(%s, array[%s], to_jsonb(%s)::jsonb, FALSE) "
                        "ELSE %s END",
                        sql_field,
                        key,
                        new_field_value,
                        key,
                        cypher_query,
                        new_field_value,
                    )
                cypherings.append(SQL("%s=%s", sql_field, new_field_value))
                conditions.append(SQL("jsonb_typeof(%s) = 'object'", sql_field))

        if cypherings:
            query = SQL(
                "UPDATE %s SET %s WHERE %s",
                SQL.identifier(table),
                SQL(",").join(cypherings),
                SQL(" OR ").join(conditions),
            )
            self.cr.execute(query)
            if with_commit:
                self.commit()

    def _get_keys_in_jsonb_column(self, table: str, field: str) -> list[str]:
        sql_field = SQL.identifier(field)
        sql_table = SQL.identifier(table)
        self.cr.execute(
            SQL(
                "SELECT count(*) FROM %s WHERE %s IS NOT NULL"
                " AND jsonb_typeof(%s) <> 'object'",
                sql_table,
                sql_field,
                sql_field,
            )
        )
        if skipped := self._get_row()[0]:
            _logger.warning(
                "%s.%s: %d row(s) hold a jsonb value that is not an object "
                "(an array or a scalar); they are left as they are.",
                table,
                field,
                skipped,
            )
        self.cr.execute(
            SQL(
                "SELECT DISTINCT jsonb_object_keys(%s) FROM %s"
                " WHERE jsonb_typeof(%s) = 'object'",
                sql_field,
                sql_table,
                sql_field,
            )
        )
        return [row[0] for row in self.cr.fetchall()]

    def _vacuum_tables(self, tables: dict[str, set[str]]) -> None:
        _logger.info("Vacuuming obfuscated tables")
        _, conn_info = get_connection_info_for_database(self.dbname)
        with psycopg.connect(**conn_info, autocommit=True) as vac_conn:
            for table in tables:
                _logger.debug("Vacuuming table %s", table)
                vac_conn.execute(SQL("VACUUM FULL %s", SQL.identifier(table)).code)

    def _confirm_insecure_operation(self) -> None:
        _logger.info(
            "The obfuscate method is not considered as safe to transfer anonymous datas to a third party."
        )
        conf_y = input(
            f"This will alter data in the database {self.dbname} and can lead to a data loss. Would you like to proceed [y/N]? "
        )
        if conf_y.strip().upper() not in ("Y", "YES"):
            self.rollback()
            sys.exit("Cancelled by user.")
        conf_db = input(
            f"Please type your database name ({self.dbname}) in UPPERCASE to confirm you understand this operation is not considered secure : "
        )
        if self.dbname.upper() != conf_db.strip():
            self.rollback()
            sys.exit("Cancelled: database name did not match.")

    def _get_password(self, opt: argparse.Namespace) -> str:
        if opt.pwd:
            return opt.pwd
        if opt.pwd_file:
            first_line = (
                pathlib.Path(opt.pwd_file)
                .read_text(encoding="utf-8")
                .partition("\n")[0]
                .strip()
            )
            if not first_line:
                self.parser.error(f"--pwd-file {opt.pwd_file!r} is empty")
            return first_line
        try:
            pwd = getpass.getpass("Cypher password: ")
        except KeyboardInterrupt:
            sys.exit("\nCancelled by user.")
        except EOFError:
            pwd = ""
        if not pwd:
            self.parser.error(
                "a cypher password is required (--pwd, --pwd-file, or the "
                "interactive prompt)"
            )
        return pwd

    def _add_arguments(self) -> None:
        parser = self.parser
        self.add_config_arguments(parser)
        pwd_group = parser.add_mutually_exclusive_group()
        pwd_group.add_argument(
            "--pwd",
            help="Cypher password. NOTE: visible to every local user via the "
            "process arguments (ps, shell history); prefer --pwd-file or the "
            "interactive prompt (default when neither flag is given).",
        )
        pwd_group.add_argument(
            "--pwd-file",
            help="Read the cypher password from the first line of this file",
        )
        parser.add_argument(
            "--fields",
            default=None,
            help="List of table.columns to obfuscate/unobfuscate, processed "
            "IN ADDITION to the built-in PII list (see --no-default-fields): "
            "table1.column1,table2.column1,table2.column2",
        )
        parser.add_argument(
            "--no-default-fields",
            action="store_true",
            default=False,
            help="Do not process the built-in PII field list; only the "
            "--fields/--file selection. Caution when unobfuscating: cover at "
            "least every field the obfuscation run processed.",
        )
        parser.add_argument(
            "--exclude",
            default=None,
            help="List of table.columns to exclude from obfuscate/unobfuscate: table1.column1,table2.column1,table2.column2",
        )
        parser.add_argument(
            "--file",
            default=None,
            help="File containing the list of table.columns to obfuscate/unobfuscate",
        )
        parser.add_argument("--unobfuscate", action="store_true", default=False)
        parser.add_argument(
            "--allfields",
            action="store_true",
            default=False,
            help="Used in unobfuscate mode, try to unobfuscate all fields. Cannot be used in obfuscate mode. Slower than specifying fields.",
        )
        parser.add_argument(
            "--vacuum",
            action="store_true",
            default=False,
            help="Vacuum database after unobfuscating",
        )
        parser.add_argument(
            "--pertablecommit",
            action="store_true",
            default=False,
            help="Commit after each table instead of a big transaction",
        )
        parser.add_argument(
            "-y",
            "--yes",
            action="store_true",
            default=False,
            help="Don't ask for manual confirmation.",
        )

    def run(self, cmdargs: list[str]) -> None:
        opt, unknown = self.parse_args(cmdargs)
        if opt.allfields and not opt.unobfuscate:
            self.parser.error("--allfields can only be used in unobfuscate mode")
        if opt.no_default_fields and not (opt.fields or opt.file or opt.allfields):
            self.parser.error(
                "--no-default-fields leaves nothing to process; add --fields or --file"
            )

        self.dbname = self.bootstrap_config(opt, extra_args=unknown)
        pwd = self._get_password(opt)

        try:
            with db_connect(self.dbname).cursor() as cr:
                self.cr = cr
                self._install_cypher_support()
                if not self._is_password_valid(pwd):
                    self.rollback()
                    sys.exit(
                        "ERROR: invalid password (the database is encrypted with a different one)."
                    )
                tables = self._get_columns_by_table(opt, pwd)
                if opt.unobfuscate:
                    self._unobfuscate_tables(opt, pwd, tables)
                else:
                    self._obfuscate_tables(opt, pwd, tables)
                self.commit()

        except psycopg.errors.ExternalRoutineInvocationException as e:
            _logger.debug("Decryption failure", exc_info=True)
            sys.exit(
                "ERROR: decryption failed — the data was obfuscated with a "
                f"different password. ({e})"
            )
        except Exception as e:
            _logger.debug("Unexpected obfuscation failure", exc_info=True)
            sys.exit(f"ERROR: {e}")
        finally:
            self.cr = None
            self._field_kinds = None
            self._field_widths = None
            _read_field_file.cache_clear()

    def _get_columns_by_table(
        self, opt: argparse.Namespace, pwd: str
    ) -> dict[str, set[str]]:
        try:
            fields = _get_fields_selected(opt)
        except ValueError as e:
            self.parser.error(str(e))

        if opt.allfields:
            fields = self._get_fields_obfuscatable()
        else:
            requested = self._get_fields_requested_explicitly(opt)
            self._load_field_catalog({t for t, _ in fields})
            absent = [f for f in fields if not self._get_field_kind(f[0], f[1])]
            if absent:
                self._report_absent_fields(
                    [f for f in absent if f in requested], level=logging.ERROR
                )
                self._report_absent_fields(
                    [f for f in absent if f not in requested], level=logging.INFO
                )
                fields = [f for f in fields if f not in absent]
            if not opt.unobfuscate:
                fields = self._exclude_fields_unfittable(fields, pwd, requested)

        _logger.info(
            "Processing fields: %s", ", ".join([f"{f[0]}.{f[1]}" for f in fields])
        )
        tables: defaultdict[str, set[str]] = defaultdict(set)
        skipped_system = []
        for table, column in fields:
            if table.startswith("ir_"):
                skipped_system.append((table, column))
            else:
                tables[table].add(column)

        if skipped_system:
            _logger.warning(
                "Refusing to obfuscate Odoo internal tables "
                "(ir_* is reserved for framework state, obfuscating "
                "it would corrupt the database). Skipping: %s",
                ", ".join(f"{t}.{f}" for t, f in skipped_system),
            )
        return tables

    @staticmethod
    def _get_fields_requested_explicitly(
        opt: argparse.Namespace,
    ) -> set[tuple[str, str]]:
        requested: set[tuple[str, str]] = set()
        if opt.fields:
            requested |= {_parse_field_spec(f) for f in opt.fields.split(",")}
        if opt.file:
            requested |= set(_read_field_file(opt.file))
        return requested

    @staticmethod
    def _report_absent_fields(fields: list[tuple[str, str]], *, level: int) -> None:
        if fields:
            _logger.log(
                level,
                "Skipping %d field(s) absent from this database (or of an "
                "unsupported column type): %s",
                len(fields),
                ", ".join(f"{t}.{c}" for t, c in fields),
            )

    def _exclude_fields_unfittable(
        self,
        fields: list[tuple[str, str]],
        pwd: str,
        requested: set[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        unfittable = self._get_fields_unfittable(fields, pwd)
        if not unfittable:
            return fields
        described = ", ".join(
            f"{t}.{c} is varchar({width}), ciphertext needs {projected}"
            for (t, c), width, projected in unfittable
        )
        if named := [f for f, _w, _p in unfittable if f in requested]:
            sys.exit(
                f"ERROR: {len(named)} field(s) you asked for cannot hold "
                f"ciphertext, and obfuscating the rest would leave them "
                f"readable: {described}. Drop them from --fields/--file, or "
                f"widen the column."
            )
        _logger.warning(
            "Skipping %d built-in field(s) whose column cannot hold ciphertext: %s",
            len(unfittable),
            described,
        )
        unfittable_fields = {field for field, _w, _p in unfittable}
        return [f for f in fields if f not in unfittable_fields]

    def _obfuscate_tables(
        self, opt: argparse.Namespace, pwd: str, tables: dict[str, set[str]]
    ) -> None:
        if not opt.yes:
            self._confirm_insecure_operation()
        _logger.info("Obfuscating datas")
        if opt.vacuum:
            _logger.warning("--vacuum only applies in unobfuscate mode; ignoring it")
        self._insert_password_marker(pwd)
        for table, columns in tables.items():
            _logger.info("Obfuscating table %s", table)
            self._update_table_values(table, columns, pwd, opt.pertablecommit)

    def _unobfuscate_tables(
        self, opt: argparse.Namespace, pwd: str, tables: dict[str, set[str]]
    ) -> None:
        if not opt.yes:
            self._confirm_insecure_operation()
        _logger.info("Unobfuscating datas")
        for table, columns in tables.items():
            _logger.info("Unobfuscating table %s", table)
            self._update_table_values(table, columns, pwd, opt.pertablecommit, True)

        partial_run = bool(opt.fields or opt.file or opt.exclude) and not opt.allfields
        if partial_run:
            _logger.warning(
                "Partial unobfuscation: keeping the stored "
                "password marker; run without --fields/"
                "--file/--exclude (or with --allfields) to "
                "remove it."
            )
        if opt.vacuum:
            self.commit()
            self._vacuum_tables(tables)
        if not partial_run:
            self._remove_password_marker()
