import argparse
import logging
import sys
import tempfile
import textwrap
import urllib.parse
import zipfile
from argparse import RawTextHelpFormatter
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import NoReturn

import requests

from ..db import SYSTEM_DBS, db_connect
from ..modules.neutralize import neutralize_database
from ..service._db_helpers import validate_db_name
from ..service.db import (
    _drop_database,
    _duplicate_database,
    _rename_database,
    dump_db,
    exp_create_database,
    exp_db_exist,
    list_dbs,
    restore_db,
)
from ..tools import config
from . import Command
from .command import refuse_maintenance_db
from .server import report_configuration

_logger = logging.getLogger(__name__)

eprint = partial(print, file=sys.stderr, flush=True)

type _SubParsers = argparse._SubParsersAction[argparse.ArgumentParser]


class Db(Command):
    """Create, drop, dump, load databases"""

    name = "db"
    description = """
        Command-line version of the database manager.

        Commands are all filestore-aware.
    """

    # No `--addons-path` here: `main()`'s bootstrap parser consumes it out of
    # argv before any command parser runs, so a declaration on this one could
    # never fire. It still works — the bootstrap feeds it to the config, and
    # `_load_cli_options` keeps it across the re-parse below.
    _CONNECTION_FLAGS = (
        ("-c", "--config"),
        ("-D", "--data-dir"),
        ("-r", "--db_user"),
        ("-w", "--db_password"),
        ("--pg_path",),
        ("--db_host",),
        ("--db_port",),
        ("--db_sslmode",),
    )

    _CONNECTION_HELP = {
        "--config": "use a specific configuration file",
        "--data-dir": "directory where to store Odoo data",
        "--db_user": "database user",
        "--db_password": "database password",
        "--pg_path": "directory holding the PostgreSQL client binaries",
        "--db_host": "database server host",
        "--db_port": "database server port",
        "--db_sslmode": "SSL mode for the database connection",
    }

    @classmethod
    def _add_connection_flags(
        cls, p: argparse.ArgumentParser, *, on_subparser: bool = False
    ) -> None:
        """Register connection/config flags on ``p``.

        Live on BOTH the parent parser and every subparser, so the user can
        write ``db -c cfg init mydb`` or ``db init mydb -c cfg``.

        :param on_subparser: register with ``default=SUPPRESS``. argparse copies
            every subparser attribute back onto the parent namespace; a plain
            ``None`` default would clobber a value passed *before* the subcommand
            (``db -c cfg drop mydb`` loses ``-c``). SUPPRESS leaves it unset.
        """
        for flags in cls._CONNECTION_FLAGS:
            help_text = cls._CONNECTION_HELP.get(flags[-1])
            if on_subparser:
                p.add_argument(*flags, default=argparse.SUPPRESS, help=help_text)
            else:
                p.add_argument(*flags, help=help_text)

    @classmethod
    def _connection_dest_flags(cls) -> dict[str, str]:
        """Map each argparse dest name to its long CLI flag.

        Derived from ``_CONNECTION_FLAGS`` so ``run``'s config-args
        reconstruction can't drift from the declared flags.
        """
        dest_flags = {}
        for flags in cls._CONNECTION_FLAGS:
            long_flag = flags[-1]
            dest_flags[long_flag.lstrip("-").replace("-", "_")] = long_flag
        return dest_flags

    def _exit_missing_subcommand(self, _args: argparse.Namespace) -> NoReturn:
        """Print full help and exit 2, the argparse code for usage errors."""
        self.parser.print_help(sys.stderr)
        sys.exit(2)

    def __init__(self) -> None:
        super().__init__()
        parser = self.parser
        self._add_connection_flags(parser)
        parser.set_defaults(func=self._exit_missing_subcommand)

        subs = parser.add_subparsers()
        subparsers = [
            build(subs)
            for build in (
                self._add_init_parser,
                self._add_load_parser,
                self._add_dump_parser,
                self._add_duplicate_parser,
                self._add_rename_parser,
                self._add_drop_parser,
                self._add_list_parser,
            )
        ]
        for sub in subparsers:
            self._add_connection_flags(sub, on_subparser=True)

    def _add_init_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        init = subs.add_parser(
            "init",
            help="Create and initialize a database",
            description="Create an empty database and install the minimum required modules",
            formatter_class=RawTextHelpFormatter,
        )
        init.set_defaults(func=self.init)
        init.add_argument(
            "database",
            help="database to create",
        )
        init.add_argument(
            "--with-demo",
            action="store_true",
            help="install demo data in the new database",
        )
        init.add_argument(
            "--force",
            action="store_true",
            help="delete database if exists",
        )
        init.add_argument(
            "--language",
            default="en_US",
            help="default language for the instance, default 'en_US'",
        )
        init.add_argument(
            "--username",
            default="admin",
            help="admin username, default 'admin'",
        )
        init.add_argument(
            "--password",
            default="admin",
            help="admin password, default 'admin'",
        )
        init.add_argument(
            "--country",
            help="country to be set on the main company",
        )
        init.epilog = textwrap.dedent("""\

                Database initialization will install the minimum required modules.
                To install more modules, use the `module install` command.
                For more info:

                $ odoo-bin module install --help
        """)
        return init

    def _add_load_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        load = subs.add_parser(
            "load",
            help="Load a dump file.",
            description="Loads a dump file into odoo, dump file can be a URL. "
            "If `database` is provided, uses that as the database name. "
            "Otherwise uses the dump file name without extension.",
        )
        load.set_defaults(func=self.load)
        load.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="delete `database` database before loading if it exists",
        )
        load.add_argument(
            "-n",
            "--neutralize",
            action="store_true",
            help="neutralize the database after restore",
        )
        load.add_argument(
            "--move",
            dest="copy",
            action="store_const",
            default=True,
            const=False,
            help="restore as a moved database, keeping its UUID instead of generating a new one",
        )
        load.add_argument(
            "database",
            nargs="?",
            help="database to create, defaults to dump file's name (without extension)",
        )
        load.add_argument(
            "dump_file",
            help="zip or pg_dump file to load",
        )
        return load

    def _add_dump_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        dump = subs.add_parser(
            "dump",
            help="Create a dump with filestore.",
            description="Creates a dump file. The dump is always in zip format "
            "(with filestore), to get pg_dump format, use "
            "dump_format argument.",
        )
        dump.set_defaults(func=self.dump)
        dump.add_argument("database", help="database to dump")
        dump.add_argument(
            "dump_path",
            nargs="?",
            default="-",
            help="path to dump to; omit or pass `-` to dump to stdout",
        )
        dump.add_argument(
            "--format",
            dest="dump_format",
            choices=("zip", "dump"),
            default="zip",
            help="format to dump in (default: `zip`).\n"
            "Supported formats: `zip`, `dump` (pg_dump format).",
        )
        dump.add_argument(
            "--no-filestore",
            action="store_const",
            dest="filestore",
            default=True,
            const=False,
            help="dump the zip without the filestore (default: included)",
        )
        return dump

    def _add_duplicate_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        duplicate = subs.add_parser(
            "duplicate",
            help="Duplicate a database including filestore.",
        )
        duplicate.set_defaults(func=self.duplicate)
        duplicate.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="delete `target` database before copying if it exists",
        )
        duplicate.add_argument(
            "-n",
            "--neutralize",
            action="store_true",
            help="neutralize the target database after duplicate",
        )
        duplicate.add_argument("source")
        duplicate.add_argument(
            "target",
            help="database to copy `source` to, must not exist unless `-f` is specified in which case it will be dropped first",
        )
        return duplicate

    def _add_rename_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        rename = subs.add_parser(
            "rename", help="Rename a database including filestore."
        )
        rename.set_defaults(func=self.rename)
        rename.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="delete `target` database before renaming if it exists",
        )
        rename.add_argument(
            "-n",
            "--neutralize",
            action="store_true",
            help="neutralize the database after rename",
        )
        rename.add_argument("source")
        rename.add_argument(
            "target",
            help="database to rename `source` to, must not exist unless `-f` is specified, in which case it will be dropped first",
        )
        return rename

    def _add_drop_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        drop = subs.add_parser("drop", help="Delete a database including filestore")
        drop.set_defaults(func=self.drop)
        drop.add_argument("database", help="database to delete")
        return drop

    def _add_list_parser(self, subs: _SubParsers) -> argparse.ArgumentParser:
        list_parser = subs.add_parser(
            "list",
            help="List databases visible to this Odoo instance",
            description="Lists the databases this instance can see, one per "
            "line. db_name from the config constrains the result the same "
            "way it does for the database-manager UI. dbfilter does NOT: "
            "it is a regex evaluated against an HTTP request host, which "
            "has no meaning outside a web request, so this command lists "
            "every database dbfilter would otherwise narrow down.",
        )
        list_parser.set_defaults(func=self.list)
        return list_parser

    def run(self, cmdargs: list[str]) -> None:
        # parse_known_args, so this command accepts the server options a
        # database operation may need (`--log-level`, `--db_maxconn`,
        # `--unaccent`, …) instead of rejecting everything it does not itself
        # declare. A typo is still caught: the config parser errors on an
        # option it does not know.
        args, unknown = self.parser.parse_known_args(cmdargs)

        dest_flags = self._connection_dest_flags()
        config_args: list[str] = []
        for key, value in vars(args).items():
            if value is None or key not in dest_flags:
                continue
            config_args.extend([dest_flags[key], value])
        config.parse_config([*config_args, *unknown], setup_logging=True)
        config["list_db"] = True
        report_configuration()

        args.func(args)

    def init(self, args: argparse.Namespace) -> None:
        self._check_target_free(args.database, force=args.force)
        self._drop_if_exists(args.database)
        exp_create_database(
            db_name=args.database,
            demo=args.with_demo,
            lang=args.language,
            login=args.username,
            user_password=args.password,
            country_code=args.country,
            phone=None,
        )

    def load(self, args: argparse.Namespace) -> None:
        db_name = args.database or Path(args.dump_file).stem
        # Before the download, not after: `restore_db` validates the name too,
        # but only once it has been handed the bytes — so a name PostgreSQL
        # cannot take (or one derived from a dump file whose stem is not a
        # legal identifier) used to cost a full fetch first.
        try:
            validate_db_name(db_name)
        except ValueError as e:
            sys.exit(f"{e}")
        self._check_target_free(db_name, force=args.force)

        url = urllib.parse.urlparse(args.dump_file)
        with ExitStack() as stack:
            if url.scheme:
                eprint(f"Fetching {args.dump_file}...", end="")
                r = stack.enter_context(
                    requests.get(args.dump_file, timeout=(10, None), stream=True)
                )
                if not r.ok:
                    sys.exit(f" unable to fetch {args.dump_file}: {r.reason}")
                downloaded = stack.enter_context(
                    tempfile.SpooledTemporaryFile(max_size=256 * 1024 * 1024)
                )
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    downloaded.write(chunk)
                downloaded.seek(0)
                dump_file = downloaded
                eprint(" done")
            else:
                eprint(f"Restoring {args.dump_file}...")
                dump_file = args.dump_file

            if not zipfile.is_zipfile(dump_file):
                sys.exit(
                    "Not a zipped dump file, use `pg_restore` to restore raw dumps,"
                    " and `psql` to execute sql dumps or scripts."
                )

            if args.force:
                self._drop_if_exists(db_name)
            restore_db(
                db=db_name,
                dump_file=dump_file,
                copy=args.copy,
                neutralize_database=args.neutralize,
            )

    def dump(self, args: argparse.Namespace) -> None:
        # NOT `_check_not_protected`: that rule is about *destructive*
        # operations, and it also refuses `config["db_template"]`. Dumping is
        # read-only, and backing up the configured creation template is a
        # perfectly ordinary thing to want — `test_db_dump_allows_the_template`
        # pins it. Only the PostgreSQL system databases are refused, because
        # dumping one of those through Odoo's filestore-aware dumper is
        # meaningless rather than dangerous.
        if args.database in SYSTEM_DBS:
            sys.exit(f"Refusing to dump system database {args.database}.")
        self._check_source_exists(args.database)
        if args.dump_path == "-":
            dump_db(args.database, sys.stdout.buffer, args.dump_format, args.filestore)
        else:
            # Checked before the dump starts rather than after: a missing
            # directory used to surface as a raw FileNotFoundError traceback,
            # and for a `dump` format it would have done so only once pg_dump
            # had already run.
            destination = Path(args.dump_path)
            if not destination.parent.is_dir():
                sys.exit(
                    f"Cannot write {args.dump_path}: {destination.parent} is not "
                    "a directory."
                )
            try:
                with destination.open("wb") as f:
                    dump_db(args.database, f, args.dump_format, args.filestore)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise

    def duplicate(self, args: argparse.Namespace) -> None:
        self._check_source_not_target(args.source, args.target)
        self._check_target_free(args.target, force=args.force)
        self._check_source_exists(args.source)
        self._drop_if_exists(args.target)
        _duplicate_database(
            args.source, args.target, neutralize_database=args.neutralize
        )

    def rename(self, args: argparse.Namespace) -> None:
        self._check_source_not_target(args.source, args.target)
        self._check_not_protected(args.source)
        self._check_target_free(args.target, force=args.force)
        self._check_source_exists(args.source)
        self._drop_if_exists(args.target)
        _rename_database(args.source, args.target)
        if args.neutralize:
            try:
                with db_connect(args.target).cursor() as cr:
                    neutralize_database(cr)
            except Exception:
                _logger.critical(
                    "An error occurred during the neutralization. THE "
                    "DATABASE IS NOT NEUTRALIZED!",
                    exc_info=True,
                )
                sys.exit(1)

    def drop(self, args: argparse.Namespace) -> None:
        self._check_not_protected(args.database)
        if not _drop_database(args.database):
            sys.exit(f"Database {args.database} does not exist.")

    def list(self, _args: argparse.Namespace) -> None:
        for db_name in list_dbs(force=True):
            print(db_name)

    def _check_not_protected(self, db_name: str) -> None:
        """Abort when ``db_name`` is a system/template database.

        PostgreSQL itself refuses to drop template databases, but with a raw
        traceback — and it happily drops ``postgres``, taking the maintenance
        DB every client tool connects to by default. One spelling of the rule,
        shared with `start`, `server` and `get_single_database`, rather than a
        private set that has to be kept in step with `is_maintenance_db`.
        """
        refuse_maintenance_db(db_name)

    def _check_target_free(self, target: str, *, force: bool) -> None:
        """Abort unless ``target`` may be (re)created.

        Pure check, no side effect: with ``force`` an occupied target is
        accepted but not dropped — the caller drops it only after validating
        its inputs, so a doomed run never destroys the database first.
        """
        self._check_not_protected(target)
        if not force and exp_db_exist(target):
            sys.exit(
                f"Target database {target} exists, aborting.\n\n"
                f"\tuse `--force` to delete the existing database anyway."
            )

    def _check_source_exists(self, source: str) -> None:
        """Abort when the source database is missing — before the target
        is dropped, not after."""
        if not exp_db_exist(source):
            sys.exit(f"Source database {source} does not exist.")

    def _check_source_not_target(self, source: str, target: str) -> None:
        """Abort when ``source`` and ``target`` are the same database.

        Without this, ``--force`` with source == target drops the only
        copy via ``_check_target_free``'s own ``_drop_if_exists(target)``
        before the operation on ``source`` ever runs, destroying the
        database instead of duplicating/renaming it.
        """
        if source == target:
            sys.exit(
                f"Source and target database are both {source!r}: aborting."
            )

    def _drop_if_exists(self, target: str) -> None:
        """Drop ``target`` (with filestore) if present; no-op otherwise.

        Calls ``_drop_database`` directly, NOT ``exp_drop``: this CLI already
        requires local trusted (shell) access, unlike ``exp_drop``'s RPC entry
        point, which the exposed-databases allowlist gate exists to protect.
        Same reasoning applies to ``drop()`` above.
        """
        self._check_not_protected(target)
        if exp_db_exist(target):
            _drop_database(target)
