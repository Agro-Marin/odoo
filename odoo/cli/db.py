import argparse
import sys
import tempfile
import textwrap
import urllib.parse
import zipfile
from argparse import RawTextHelpFormatter
from contextlib import ExitStack
from functools import partial
from pathlib import Path

import requests

from ..db import db_connect
from ..modules.neutralize import neutralize_database
from ..service.db import (
    dump_db,
    exp_create_database,
    exp_db_exist,
    exp_drop,
    exp_duplicate_database,
    exp_rename,
    restore_db,
)
from ..tools import config
from . import Command
from .server import report_configuration

eprint = partial(print, file=sys.stderr, flush=True)


class Db(Command):
    """Create, drop, dump, load databases"""

    name = "db"
    description = """
        Command-line version of the database manager.

        Commands are all filestore-aware.
    """

    _CONNECTION_FLAGS = (
        ("-c", "--config"),
        ("-D", "--data-dir"),
        ("--addons-path",),
        ("-r", "--db_user"),
        ("-w", "--db_password"),
        ("--pg_path",),
        ("--db_host",),
        ("--db_port",),
        ("--db_sslmode",),
    )

    @classmethod
    def _add_connection_flags(cls, p: argparse.ArgumentParser) -> None:
        """Register connection/config flags on ``p``.

        These flags live on BOTH the parent parser and every subparser so the
        user can write either ``db -c cfg init mydb`` or the more natural
        ``db init mydb -c cfg`` (matches ``module install`` UX).
        """
        for flags in cls._CONNECTION_FLAGS:
            p.add_argument(*flags)

    def run(self, cmdargs: list[str]) -> None:
        parser = self.parser
        self._add_connection_flags(parser)
        parser.set_defaults(func=lambda _: sys.exit(parser.format_help()))

        subs = parser.add_subparsers()

        # INIT ----------------------------------

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

        # LOAD ----------------------------------

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
            "database",
            nargs="?",
            help="database to create, defaults to dump file's name (without extension)",
        )
        load.add_argument(
            "dump_file",
            help="zip or pg_dump file to load",
        )

        # DUMP ----------------------------------

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
            help="if provided, database is dumped to specified path, otherwise "
            "or if `-`, dumped to stdout",
        )
        dump.add_argument(
            "--format",
            dest="dump_format",
            choices=("zip", "dump"),
            default="zip",
            help="if provided, database is dumped used the specified format, "
            "otherwise defaults to `zip`.\n"
            "Supported formats are `zip`, `dump` (pg_dump format) ",
        )
        dump.add_argument(
            "--no-filestore",
            action="store_const",
            dest="filestore",
            default=True,
            const=False,
            help="if passed, zip database is dumped without filestore "
            "(default: filestore is included)",
        )

        # DUPLICATE -----------------------------

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

        # RENAME --------------------------------

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

        # DROP ----------------------------------

        drop = subs.add_parser("drop", help="Delete a database including filestore")
        drop.set_defaults(func=self.drop)
        drop.add_argument("database", help="database to delete")

        # Also accept connection flags AFTER the subcommand name (matches
        # `module install -c cfg <mod>` UX).
        for sub in (init, load, dump, duplicate, rename, drop):
            self._add_connection_flags(sub)

        args = parser.parse_args(cmdargs)

        # Map argparse namespace keys to config CLI flags. The two underscore-form
        # keys must be hyphenated; everything else passes through as `--<key>`.
        flag_overrides = {"data_dir": "--data-dir", "addons_path": "--addons-path"}
        passthrough_keys = ("config", "data_dir", "addons_path")
        config_args: list[str] = []
        for key, value in vars(args).items():
            if value is None:
                continue
            if key not in passthrough_keys and not key.startswith(("db_", "pg_")):
                continue
            config_args.extend([flag_overrides.get(key, f"--{key}"), value])
        config.parse_config(config_args, setup_logging=True)
        # force db management active to bypass check when only a
        # `check_db_management_enabled` version is available.
        config["list_db"] = True
        report_configuration()

        args.func(args)

    def init(self, args: argparse.Namespace) -> None:
        self._check_target(args.database, delete_if_exists=args.force)
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
        self._check_target(db_name, delete_if_exists=args.force)

        url = urllib.parse.urlparse(args.dump_file)
        # ExitStack ties the spooled temp file's lifetime to the function:
        # restore_db must read from it after the requests.get with-block
        # closes, so a plain `with tempfile.SpooledTemporaryFile(...) as f:`
        # at the inner scope would not work.
        with ExitStack() as stack:
            if url.scheme:
                eprint(f"Fetching {args.dump_file}...", end="")
                # Split connect/read timeouts: short connect (10s) catches
                # bad URLs, unlimited read accommodates multi-GB production
                # dumps. Stream to a spooled file so the whole response
                # never lives in RAM; close the response so connections
                # return to the pool.
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

            restore_db(
                db=db_name,
                dump_file=dump_file,
                copy=True,
                neutralize_database=args.neutralize,
            )

    def dump(self, args: argparse.Namespace) -> None:
        if args.dump_path == "-":
            dump_db(args.database, sys.stdout.buffer, args.dump_format, args.filestore)
        else:
            with Path(args.dump_path).open("wb") as f:
                dump_db(args.database, f, args.dump_format, args.filestore)

    def duplicate(self, args: argparse.Namespace) -> None:
        self._check_target(args.target, delete_if_exists=args.force)
        exp_duplicate_database(
            args.source, args.target, neutralize_database=args.neutralize
        )

    def rename(self, args: argparse.Namespace) -> None:
        self._check_target(args.target, delete_if_exists=args.force)
        exp_rename(args.source, args.target)
        if args.neutralize:
            with db_connect(args.target).cursor() as cr:
                neutralize_database(cr)

    def drop(self, args: argparse.Namespace) -> None:
        if not exp_drop(args.database):
            sys.exit(f"Database {args.database} does not exist.")

    def _check_target(self, target: str, *, delete_if_exists: bool) -> None:
        if exp_db_exist(target):
            if delete_if_exists:
                exp_drop(target)
            else:
                sys.exit(
                    f"Target database {target} exists, aborting.\n\n"
                    f"\tuse `--force` to delete the existing database anyway."
                )
