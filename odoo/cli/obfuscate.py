import functools
import logging
import pathlib
import sys
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import psycopg

from odoo.db import connection_info_for
from odoo.modules.registry import Registry
from odoo.tools import SQL, config

from . import Command, build_config_args

if TYPE_CHECKING:
    from odoo.db import Cursor

_logger = logging.getLogger(__name__)

# Fields stored as jsonb whose value is an untyped NULL break jsonb_set: any
# NULL argument to jsonb_set returns NULL, which would wipe the whole column
# for rows that don't cover every cross-table key. See the CASE guard in
# convert_table below.


def _parse_field_spec(spec: str) -> tuple[str, str]:
    """Parse a ``table.column`` field specification into a 2-tuple.

    Raises ValueError if the spec doesn't have exactly one dot.
    """
    parts = spec.strip().split(".")
    if len(parts) != 2 or not all(parts):
        msg = f"Invalid field specification {spec!r}: expected 'table.column'"
        raise ValueError(msg)
    return parts[0], parts[1]


def _ensure_cr(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: raise if the wrapped Obfuscate method has no open cursor."""

    @functools.wraps(func)
    def check_cr(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not self.cr:
            msg = "No database connection"
            raise RuntimeError(msg)
        return func(self, *args, **kwargs)

    return check_cr


class Obfuscate(Command):
    """Obfuscate data in a given odoo database"""

    def __init__(self) -> None:
        super().__init__()
        self.cr: Cursor | None = None
        self.dbname: str = ""
        self.registry: Registry | None = None

    @_ensure_cr
    def begin(self) -> None:
        # psycopg opens an implicit transaction on first execute (autocommit=False),
        # so an explicit BEGIN is unnecessary and triggers a PG warning.
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
        except Exception as e:
            _logger.error("Error checking password: %s", e)
        return False

    @_ensure_cr
    def clear_pwd(self) -> None:
        """Unset password to cypher/uncypher datas"""
        self.cr.execute("DELETE FROM ir_config_parameter WHERE key='odoo_cyph_pwd'")

    def cypher_string(self, sql_field: SQL, password: str) -> SQL:
        # don't double cypher fields
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

    def check_field(self, table: str, field: str) -> str | bool:
        qry = "SELECT udt_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s AND table_schema = current_schema"
        self.cr.execute(qry, [table, field])
        if self.cr.rowcount == 1:
            res = self.cr.fetchone()
            if res[0] in ["text", "varchar"]:
                # Doesn t work for selection fields ...
                return "string"
            if res[0] == "jsonb":
                return "json"
        return False

    def get_all_fields(self) -> list[tuple[str, str]]:
        # Use starts_with(table_name, 'ir_') — LIKE 'ir_%' would also match
        # tables like 'irrelevant' because '_' is a LIKE wildcard.
        qry = (
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema"
            " AND udt_name IN ('text', 'varchar', 'jsonb')"
            " AND NOT starts_with(table_name, 'ir_')"
            " ORDER BY 1, 2"
        )
        self.cr.execute(qry)
        return self.cr.fetchall()

    def convert_table(
        self,
        table: str,
        fields: set[str] | list[str],
        pwd: str,
        with_commit: bool = False,
        unobfuscate: bool = False,
    ) -> None:
        cypherings = []
        cyph_fct = self.uncypher_string if unobfuscate else self.cypher_string

        for field in fields:
            field_type = self.check_field(table, field)
            sql_field = SQL.identifier(field)
            if field_type == "string":
                cypher_query = cyph_fct(sql_field, pwd)
                cypherings.append(SQL("%s=%s", SQL.identifier(field), cypher_query))
            elif field_type == "json":
                # Gather keys seen anywhere in the column, then build a
                # nested jsonb_set that encrypts each key per-row. The
                # CASE guard below is load-bearing: a plain
                # jsonb_set(d, path, NULL, FALSE) returns NULL for the
                # whole expression whenever the row is missing a key that
                # another row has — which would wipe the column for that
                # row. Guarding on `d->>key IS NOT NULL` skips the
                # jsonb_set entirely when the row either has no such key
                # or holds JSON null.
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

        if cypherings:
            query = SQL(
                "UPDATE %s SET %s",
                SQL.identifier(table),
                SQL(",").join(cypherings),
            )
            self.cr.execute(query)
            if with_commit:
                self.commit()
                self.begin()

    def _vacuum_tables(self, tables: dict[str, set[str]]) -> None:
        """Run ``VACUUM FULL`` on each table via a dedicated autocommit connection.

        PostgreSQL refuses ``VACUUM`` inside a transaction block, so we cannot
        reuse the registry cursor. We open a raw psycopg connection with
        ``autocommit=True`` and issue one ``VACUUM`` per table.
        """
        _logger.info("Vacuuming obfuscated tables")
        _, conn_info = connection_info_for(self.dbname)
        with psycopg.connect(**conn_info, autocommit=True) as vac_conn:
            for table in tables:
                _logger.debug("Vacuuming table %s", table)
                vac_conn.execute(SQL("VACUUM FULL %s", SQL.identifier(table)).code)

    def confirm_not_secure(self) -> bool:
        """Prompt the user for double-confirmation of the destructive run.

        Exits with status 1 if the user cancels, so shell pipelines
        (`obfuscate … && rsync …`) treat cancellation as a failure and
        do not proceed to ship unencrypted data.
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

    def run(self, cmdargs: list[str]) -> None:
        parser = self.parser
        self.add_config_arguments(parser)
        parser.add_argument("--pwd", required=True, help="Cypher password")
        parser.add_argument(
            "--fields",
            default=None,
            help="List of table.columns to obfuscate/unobfuscate: table1.column1,table2.column1,table2.column2",
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

        # No explicit empty-args guard: --pwd is required=True so argparse
        # will emit a clear "--pwd is required" error on empty invocation.
        opt = parser.parse_args(cmdargs)

        if opt.allfields and not opt.unobfuscate:
            parser.error("--allfields can only be used in unobfuscate mode")

        config_args = build_config_args(opt.config, opt.db_name)
        config.parse_config(config_args, setup_logging=True)
        self.dbname = self.require_single_database(opt)

        try:
            self.registry = Registry(self.dbname)
            with self.registry.cursor() as cr:
                self.cr = cr
                self.begin()
                if self.check_pwd(opt.pwd):
                    fields = [
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
                    ]

                    if opt.fields:
                        if not opt.allfields:
                            fields += [
                                _parse_field_spec(f) for f in opt.fields.split(",")
                            ]
                        else:
                            _logger.warning(
                                "--allfields is set: --fields and the built-in "
                                "field list are both ignored, every text field "
                                "in the schema will be processed"
                            )
                    if opt.file:
                        with pathlib.Path(opt.file).open(encoding="utf-8") as f:
                            fields += [
                                _parse_field_spec(line) for line in f if line.strip()
                            ]
                    if opt.exclude:
                        if not opt.allfields:
                            excluded = {
                                _parse_field_spec(e) for e in opt.exclude.split(",")
                            }
                            fields = [f for f in fields if f not in excluded]
                        else:
                            _logger.warning("--allfields is set: --exclude is ignored")

                    if opt.allfields:
                        fields = self.get_all_fields()
                    else:
                        invalid_fields = [
                            f for f in fields if not self.check_field(f[0], f[1])
                        ]
                        if invalid_fields:
                            _logger.error(
                                "Invalid fields: %s",
                                ", ".join([f"{f[0]}.{f[1]}" for f in invalid_fields]),
                            )
                            fields = [f for f in fields if f not in invalid_fields]

                    if not opt.unobfuscate and not opt.yes:
                        self.confirm_not_secure()

                    _logger.info(
                        "Processing fields: %s",
                        ", ".join([f"{f[0]}.{f[1]}" for f in fields]),
                    )
                    tables = defaultdict(set)
                    skipped_system = []

                    for t, f in fields:
                        if t.startswith("ir_"):
                            skipped_system.append((t, f))
                        else:
                            tables[t].add(f)

                    if skipped_system:
                        _logger.warning(
                            "Refusing to obfuscate Odoo internal tables "
                            "(ir_* is reserved for framework state, obfuscating "
                            "it would corrupt the database). Skipping: %s",
                            ", ".join(f"{t}.{f}" for t, f in skipped_system),
                        )

                    if opt.unobfuscate:
                        _logger.info("Unobfuscating datas")
                        for table in tables:
                            _logger.info("Unobfuscating table %s", table)
                            self.convert_table(
                                table,
                                tables[table],
                                opt.pwd,
                                opt.pertablecommit,
                                True,
                            )

                        if opt.vacuum:
                            # VACUUM FULL cannot run inside a transaction
                            # block (Postgres raises ActiveSqlTransaction),
                            # so commit pending work and run each VACUUM on
                            # a dedicated autocommit psycopg connection,
                            # bypassing Odoo's transactional Cursor.
                            self.commit()
                            self._vacuum_tables(tables)
                            # Resume the registry cursor with a fresh txn
                            # for clear_pwd below.
                            self.begin()
                        self.clear_pwd()
                    else:
                        _logger.info("Obfuscating datas")
                        self.set_pwd(opt.pwd)
                        for table in tables:
                            _logger.info("Obfuscating table %s", table)
                            self.convert_table(
                                table,
                                tables[table],
                                opt.pwd,
                                opt.pertablecommit,
                            )

                    self.commit()
                else:
                    self.rollback()
                    sys.exit(
                        "ERROR: invalid password (the database is encrypted with a different one)."
                    )

        except Exception as e:
            sys.exit(f"ERROR: {e}")
        finally:
            # The `with registry.cursor()` context has already released the
            # cursor; drop our reference so `_ensure_cr` can detect reuse
            # of a closed cursor (tests that instantiate Obfuscate twice, etc.).
            self.cr = None
