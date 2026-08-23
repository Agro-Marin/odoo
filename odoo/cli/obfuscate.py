import argparse
import functools
import getpass
import logging
import pathlib
import sys
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import psycopg

from odoo.db import connection_info_for, db_connect
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
    """Parse a ``table.column`` field specification into a 2-tuple.

    :raises ValueError: if *spec* is not of the form ``table.column``
    """
    parts = spec.strip().split(".")
    if len(parts) != 2 or not all(parts):
        msg = f"Invalid field specification {spec!r}: expected 'table.column'"
        raise ValueError(msg)
    return parts[0], parts[1]


def _select_fields(opt: argparse.Namespace) -> list[tuple[str, str]]:
    """Resolve the requested ``(table, column)`` pairs from CLI options.

    Pure selection; schema validation and ``--allfields`` expansion need a
    cursor and stay in ``run``. ``--allfields`` ignores manual selections.

    :raises ValueError: on a malformed ``table.column`` spec
    """
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
            with pathlib.Path(opt.file).open(encoding="utf-8") as f:
                fields += [_parse_field_spec(line) for line in f if line.strip()]
    if opt.exclude:
        if opt.allfields:
            _logger.warning("--allfields is set: ignoring --exclude")
        else:
            excluded = {_parse_field_spec(e) for e in opt.exclude.split(",")}
            fields = [f for f in fields if f not in excluded]
    return fields


def _ensure_cr(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: raise if the wrapped Obfuscate method has no open cursor."""

    @functools.wraps(func)
    def check_cr(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not self.cr:
            msg = "No database connection"
            raise RuntimeError(msg)
        return func(self, *args, **kwargs)

    return check_cr


class Obfuscate(DatabaseCommand):
    """Obfuscate data in a given odoo database"""

    def __init__(self) -> None:
        super().__init__()
        self.cr: Cursor | None = None
        self.dbname: str = ""
        self._field_kinds: dict[tuple[str, str], str] | None = None
        self._field_widths: dict[tuple[str, str], int] | None = None
        self.add_arguments()

    @_ensure_cr
    def _ensure_pgcrypto(self) -> None:
        self.cr.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    @_ensure_cr
    def commit(self) -> None:
        self.cr.commit()

    @_ensure_cr
    def rollback(self) -> None:
        self.cr.rollback()

    @_ensure_cr
    def set_pwd(self, pwd: str) -> None:
        """Set password to cypher/uncypher datas"""
        self.cr.execute(
            "INSERT INTO ir_config_parameter (key, value) VALUES ('odoo_cyph_pwd', 'odoo_cyph_'||encode(pgp_sym_encrypt(%s, %s), 'base64')) ON CONFLICT(key) DO NOTHING",
            [pwd, pwd],
        )

    @_ensure_cr
    def check_pwd(self, pwd: str) -> bool:
        """If password is set, check if it's valid"""
        uncypher_pwd = self.uncypher_string(SQL.identifier("value"), pwd)

        try:
            query = SQL(
                "SELECT %s FROM ir_config_parameter WHERE key='odoo_cyph_pwd'",
                uncypher_pwd,
            )
            self.cr.execute(query)
            if self.cr.rowcount == 0 or (
                self.cr.rowcount == 1 and self.cr.fetchone()[0] == pwd
            ):
                return True
        except psycopg.errors.ExternalRoutineInvocationException as e:
            _logger.info("Password check failed: %s", e)
        return False

    @_ensure_cr
    def clear_pwd(self) -> None:
        """Unset password to cypher/uncypher datas"""
        self.cr.execute("DELETE FROM ir_config_parameter WHERE key='odoo_cyph_pwd'")

    def cypher_string(self, sql_field: SQL, password: str) -> SQL:
        return SQL(
            """CASE WHEN starts_with(%(field_name)s, 'odoo_cyph_') THEN %(field_name)s ELSE 'odoo_cyph_'||encode(pgp_sym_encrypt(%(field_name)s, %(pwd)s), 'base64') END""",
            field_name=sql_field,
            pwd=password,
        )

    def uncypher_string(self, sql_field: SQL, password: str) -> SQL:
        return SQL(
            """CASE WHEN starts_with(%(field_name)s, 'odoo_cyph_') THEN pgp_sym_decrypt(decode(substring(%(field_name)s, 11)::text, 'base64'), %(pwd)s) ELSE %(field_name)s END""",
            field_name=sql_field,
            pwd=password,
        )

    @staticmethod
    def _kind_of(udt_name: str) -> str | None:
        """Map a PostgreSQL ``udt_name`` to the obfuscation kind."""
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

    def _index_rows(self, rows: list[tuple]) -> None:
        """Index catalog rows into the kind and column-width caches."""
        self._field_kinds = {}
        self._field_widths = {}
        for table, column, udt, max_length in rows:
            if kind := self._kind_of(udt):
                self._field_kinds[table, column] = kind
                if max_length is not None:
                    self._field_widths[table, column] = max_length

    def _prefetch_field_kinds(self, tables: set[str] | list[str]) -> None:
        """Cache the obfuscation kind of every text/varchar/jsonb column of
        ``tables`` in one catalog query, so ``check_field`` becomes a dict
        lookup instead of an ``information_schema`` probe per field. The
        cache holds only string/json columns, so a miss reads the same as the
        per-field query's "absent or unsupported".
        """
        self._field_kinds = {}
        self._field_widths = {}
        if not tables:
            return
        self.cr.execute(
            f"{self._CATALOG_COLUMNS} AND table_name = ANY(%s)",
            [list(tables)],
        )
        self._index_rows(self.cr.fetchall())

    def check_field(self, table: str, field: str) -> str | None:
        """Return the processing kind for ``table.column``: ``'string'``,
        ``'json'``, or None when the column is absent or unsupported."""
        if self._field_kinds is not None:
            return self._field_kinds.get((table, field))
        qry = "SELECT udt_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s AND table_schema = current_schema"
        self.cr.execute(qry, [table, field])
        if self.cr.rowcount == 1:
            return self._kind_of(self.cr.fetchone()[0])
        return None

    def find_narrow_fields(
        self, fields: list[tuple[str, str]]
    ) -> list[tuple[tuple[str, str], int]]:
        """Return the ``((table, column), width)`` pairs too narrow to hold
        ciphertext, so obfuscation can refuse them before it writes anything.

        ``pgp_sym_encrypt`` output, base64-encoded and prefixed, runs to
        hundreds of characters whatever the input, so a ``varchar(n)`` column
        raises ``value too long for type character varying(n)`` mid-``UPDATE``.
        That aborted the run partway: with ``--pertablecommit`` the tables
        already processed stayed obfuscated and the password marker stayed
        committed, with nothing recording where the run stopped.
        ``res_country.code`` is ``varchar(2)`` on any database.
        """
        return [
            (field, self._field_widths[field])
            for field in fields
            if field in (self._field_widths or {})
        ]

    def get_all_fields(self) -> list[tuple[str, str]]:
        self.cr.execute(
            f"{self._CATALOG_COLUMNS}"
            " AND NOT starts_with(table_name, 'ir_')"
            " ORDER BY 1, 2"
        )
        rows = self.cr.fetchall()
        self._index_rows(rows)
        return [(table, column) for table, column, _udt, _len in rows]

    def convert_table(
        self,
        table: str,
        fields: set[str] | list[str],
        pwd: str,
        with_commit: bool = False,
        unobfuscate: bool = False,
    ) -> None:
        cypherings = []
        conditions = []
        cyph_fct = self.uncypher_string if unobfuscate else self.cypher_string

        for field in fields:
            field_type = self.check_field(table, field)
            sql_field = SQL.identifier(field)
            if field_type == "string":
                cypher_query = cyph_fct(sql_field, pwd)
                cypherings.append(SQL("%s=%s", SQL.identifier(field), cypher_query))
                if unobfuscate:
                    conditions.append(SQL("starts_with(%s, 'odoo_cyph_')", sql_field))
                else:
                    conditions.append(
                        SQL(
                            "(%s IS NOT NULL AND NOT starts_with(%s, 'odoo_cyph_'))",
                            sql_field,
                            sql_field,
                        )
                    )
            elif field_type == "json":
                new_field_value = sql_field
                self.cr.execute(
                    SQL(
                        "SELECT DISTINCT jsonb_object_keys(%s) FROM %s",
                        sql_field,
                        SQL.identifier(table),
                    )
                )
                keys = [k[0] for k in self.cr.fetchall()]
                for key in keys:
                    cypher_query = cyph_fct(SQL("%s->>%s", sql_field, key), pwd)
                    new_field_value = SQL(
                        "CASE WHEN %s->>%s IS NOT NULL "
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
                conditions.append(SQL("%s IS NOT NULL", sql_field))

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

    def _vacuum_tables(self, tables: dict[str, set[str]]) -> None:
        """Run ``VACUUM FULL`` per table on a dedicated autocommit connection.

        PostgreSQL refuses ``VACUUM`` inside a transaction block, so the pooled
        cursor can't be reused.
        """
        _logger.info("Vacuuming obfuscated tables")
        _, conn_info = connection_info_for(self.dbname)
        with psycopg.connect(**conn_info, autocommit=True) as vac_conn:
            for table in tables:
                _logger.debug("Vacuuming table %s", table)
                vac_conn.execute(SQL("VACUUM FULL %s", SQL.identifier(table)).code)

    def confirm_not_secure(self) -> bool:
        """Prompt for double-confirmation of the destructive run.

        Exits non-zero on cancel, so a pipeline (`obfuscate … && rsync …`)
        won't go on to ship unencrypted data.
        """
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
        return True

    def _resolve_password(self, opt: argparse.Namespace) -> str:
        """Resolve the cypher password from ``--pwd``, ``--pwd-file``, or an
        interactive prompt, in that order. The prompt is preferred: ``--pwd``
        exposes the password via process args and shell history.
        """
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

    def add_arguments(self) -> None:
        """Declare the command's options on ``self.parser``.

        In ``__init__`` rather than in ``run`` so the parser is complete on a
        constructed command: a test (or a completion/doc generator) can read
        the option set without executing an obfuscation run, and calling
        ``run`` twice on one instance no longer raises ``ArgumentError``.
        """
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
        pwd = self._resolve_password(opt)

        try:
            with db_connect(self.dbname).cursor() as cr:
                self.cr = cr
                self._ensure_pgcrypto()
                if not self.check_pwd(pwd):
                    self.rollback()
                    sys.exit(
                        "ERROR: invalid password (the database is encrypted with a different one)."
                    )
                tables = self._resolve_targets(opt)
                if opt.unobfuscate:
                    self._unobfuscate(opt, pwd, tables)
                else:
                    self._obfuscate(opt, pwd, tables)
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

    def _resolve_targets(self, opt: argparse.Namespace) -> dict[str, set[str]]:
        """Resolve the CLI selection into ``{table: {column, ...}}``.

        Everything that can disqualify a column happens here, before a single
        row is written: absent from the schema, an ``ir_*`` table, or (when
        obfuscating) too narrow to hold ciphertext.
        """
        try:
            fields = _select_fields(opt)
        except ValueError as e:
            self.parser.error(str(e))

        if opt.allfields:
            fields = self.get_all_fields()
        else:
            requested = self._explicitly_requested(opt)
            self._prefetch_field_kinds({t for t, _ in fields})
            absent = [f for f in fields if not self.check_field(f[0], f[1])]
            if absent:
                # A default-list field missing because its module is not
                # installed is the normal case on any small database — 17 of
                # the 28 on a base-only one — and was reported at ERROR, which
                # trained the reader to skip the line that also reports the
                # typo they made in --fields.
                self._report_absent(
                    [f for f in absent if f in requested], level=logging.ERROR
                )
                self._report_absent(
                    [f for f in absent if f not in requested], level=logging.INFO
                )
                fields = [f for f in fields if f not in absent]
            if not opt.unobfuscate:
                fields = self._drop_narrow_fields(fields)

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
    def _explicitly_requested(opt: argparse.Namespace) -> set[tuple[str, str]]:
        """The ``(table, column)`` pairs the user named, as opposed to the
        ones that came from :data:`DEFAULT_FIELDS`."""
        requested: set[tuple[str, str]] = set()
        if opt.fields:
            requested |= {_parse_field_spec(f) for f in opt.fields.split(",")}
        if opt.file:
            with pathlib.Path(opt.file).open(encoding="utf-8") as f:
                requested |= {_parse_field_spec(line) for line in f if line.strip()}
        return requested

    @staticmethod
    def _report_absent(fields: list[tuple[str, str]], *, level: int) -> None:
        if fields:
            _logger.log(
                level,
                "Skipping %d field(s) absent from this database (or of an "
                "unsupported column type): %s",
                len(fields),
                ", ".join(f"{t}.{c}" for t, c in fields),
            )

    def _drop_narrow_fields(
        self, fields: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Drop the columns whose declared width cannot hold ciphertext."""
        narrow = self.find_narrow_fields(fields)
        if narrow:
            _logger.warning(
                "Skipping %d column(s) too narrow to hold ciphertext (the "
                "UPDATE would fail with 'value too long' partway through the "
                "run): %s",
                len(narrow),
                ", ".join(f"{t}.{c} varchar({width})" for (t, c), width in narrow),
            )
        narrow_fields = {field for field, _width in narrow}
        return [f for f in fields if f not in narrow_fields]

    def _obfuscate(
        self, opt: argparse.Namespace, pwd: str, tables: dict[str, set[str]]
    ) -> None:
        if not opt.yes:
            self.confirm_not_secure()
        _logger.info("Obfuscating datas")
        if opt.vacuum:
            _logger.warning("--vacuum only applies in unobfuscate mode; ignoring it")
        self.set_pwd(pwd)
        for table, columns in tables.items():
            _logger.info("Obfuscating table %s", table)
            self.convert_table(table, columns, pwd, opt.pertablecommit)

    def _unobfuscate(
        self, opt: argparse.Namespace, pwd: str, tables: dict[str, set[str]]
    ) -> None:
        _logger.info("Unobfuscating datas")
        for table, columns in tables.items():
            _logger.info("Unobfuscating table %s", table)
            self.convert_table(table, columns, pwd, opt.pertablecommit, True)

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
            self.clear_pwd()
