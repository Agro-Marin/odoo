import argparse
import contextlib
import logging
import re
import sys
from collections.abc import Callable, Generator
from inspect import cleandoc
from pathlib import Path
from typing import NoReturn

import odoo.cli
import odoo.init  # noqa: F401  imported for the bootstrap side effect (gc, monkeypatches)
from odoo.db import is_maintenance_db
from odoo.modules import initialize_sys_path, load_script
from odoo.tools import config

_logger = logging.getLogger(__name__)

COMMAND_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\Z")
PROG_NAME = Path(sys.argv[0]).name
DEFAULT_COMMAND = "server"
"""Command dispatched when argv names none; also rendered by ``help``."""
MAINTENANCE_DB_MESSAGE = "Refusing to operate on system or template database {db_name}."
"""One wording for the one rule :func:`refuse_maintenance_db` enforces.

A neutral verb on purpose: the same sentence has to read correctly for serving,
creating, dropping and renaming, which the two it replaces ("use", "touch") each
did for only half of those.
"""
commands: dict[str, type[Command]] = {}
"""All loaded commands"""


def build_config_args(
    config_file: str | None = None,
    db_name: str | None = None,
    *,
    no_http: bool = True,
    extra_args: list[str] | None = None,
) -> list[str]:
    args = []
    if no_http:
        args.append("--no-http")
    if config_file:
        args.extend(["-c", config_file])
    if db_name:
        args.extend(["-d", db_name])
    if extra_args:
        args.extend(extra_args)
    return args


def get_single_database(
    db_names: list[str] | None,
    *,
    allow_none: bool = False,
    error_handler: Callable[[str], NoReturn] | None = None,
) -> str | None:
    if error_handler is None:
        error_handler = sys.exit

    if not db_names:
        if allow_none:
            return None
        error_handler(
            "No database specified. Use -d/--database or set db_name in the config file."
        )
        return None

    if len(db_names) > 1:
        error_handler(
            f"Multiple databases configured ({db_names}); "
            "please provide a single one via -d/--database."
        )
        return None

    db_name = db_names[0]
    if is_maintenance_db(db_name):
        error_handler(MAINTENANCE_DB_MESSAGE.format(db_name=db_name))
        return None

    return db_name


def refuse_maintenance_db(
    db_name: str,
    *,
    error_handler: Callable[[str], NoReturn] | None = None,
) -> None:
    if error_handler is None:
        error_handler = sys.exit
    if is_maintenance_db(db_name):
        error_handler(MAINTENANCE_DB_MESSAGE.format(db_name=db_name))


@contextlib.contextmanager
def odoo_env(
    db_name: str,
    *,
    readonly: bool = False,
    context: dict | None = None,
    uid: int | None = None,
    new_registry: bool = False,
) -> Generator:
    from odoo import SUPERUSER_ID
    from odoo.api import Environment
    from odoo.modules.registry import Registry

    if uid is None:
        uid = SUPERUSER_ID
    if context is None:
        context = {}

    registry_cls = Registry.new if new_registry else Registry
    with registry_cls(db_name).cursor(readonly=readonly) as cr:
        yield Environment(cr, uid, context)


class Command:
    name: str | None = None
    description: str | None = None
    epilog: str | None = None

    def __init__(self) -> None:
        self._parser: argparse.ArgumentParser | None = None

    def run(self, args: list[str]) -> None:
        raise NotImplementedError(
            f"{type(self).__qualname__} must override `run(self, args)`"
        )

    def __init_subclass__(cls, register: bool = True) -> None:
        if not register:
            return
        cls.name = cls.name or cls.__name__.lower()
        module = cls.__module__.rpartition(".")[2]
        if not cls.is_valid_name(cls.name):
            raise ValueError(
                f"Command name {cls.name!r} must match {COMMAND_NAME_RE.pattern!r}"
            )
        if cls.name != module:
            raise ValueError(
                f"Command name {cls.name!r} must match Module name {module!r}"
            )
        if cls.run is Command.run:
            raise TypeError(
                f"Command subclass {cls.__qualname__!r} must override "
                "`run(self, args: list[str]) -> None`"
            )
        if cls.name in commands:
            _logger.warning(
                "Command %r redefined: was %s, now %s (second registration wins)",
                cls.name,
                commands[cls.name].__module__,
                cls.__module__,
            )
        commands[cls.name] = cls

    @property
    def prog(self) -> str:
        return f"{PROG_NAME} [--addons-path=PATH,...] {self.name}"

    @property
    def parser(self) -> argparse.ArgumentParser:
        if self._parser is None:
            self._parser = argparse.ArgumentParser(
                formatter_class=argparse.RawDescriptionHelpFormatter,
                prog=self.prog,
                description=cleandoc(self.description or self.__doc__ or ""),
                epilog=cleandoc(self.epilog or ""),
            )
        return self._parser

    @classmethod
    def is_valid_name(cls, name: str) -> re.Match[str] | None:
        return COMMAND_NAME_RE.match(name)


class DatabaseCommand(Command, register=False):
    def add_config_arguments(
        self, parser: argparse.ArgumentParser, *, on_subparser: bool = False
    ) -> None:
        extra = {"default": argparse.SUPPRESS} if on_subparser else {"default": None}
        parser.add_argument(
            "-c",
            "--config",
            dest="config",
            help="use a specific configuration file",
            **extra,
        )
        parser.add_argument(
            "-d",
            "--database",
            dest="db_name",
            help="database name, connection details will be taken from the config file",
            **extra,
        )
        parser.add_argument(
            "-D",
            "--data-dir",
            dest="data_dir",
            help="directory where to store Odoo data",
            **extra,
        )

    def parse_args(self, args: list[str]) -> tuple[argparse.Namespace, list[str]]:
        return self.parser.parse_known_args(args)

    def bootstrap_config(
        self,
        parsed_args: argparse.Namespace,
        *,
        allow_none: bool = False,
        extra_args: list[str] | None = None,
    ) -> str | None:
        forwarded = list(extra_args or [])
        if getattr(parsed_args, "data_dir", None):
            forwarded = ["-D", parsed_args.data_dir, *forwarded]
        config_args = build_config_args(
            parsed_args.config,
            parsed_args.db_name,
            extra_args=forwarded or None,
        )
        config.parse_config(config_args, setup_logging=True)
        return self.require_single_database(parsed_args, allow_none=allow_none)

    def require_single_database(
        self,
        parsed_args: argparse.Namespace,
        *,
        allow_none: bool = False,
    ) -> str | None:
        db_name = get_single_database(
            config["db_name"],
            allow_none=allow_none,
            error_handler=self.parser.error,
        )
        if db_name is not None:
            parsed_args.db_name = db_name
        return db_name


def load_internal_commands() -> None:
    for path in odoo.cli.__path__:
        for module in Path(path).iterdir():
            if module.suffix != ".py" or module.stem.startswith("_"):
                continue
            __import__(f"odoo.cli.{module.stem}")


def load_addons_commands(command: str | None = None) -> None:
    if command is None:
        command = "*"
    elif not Command.is_valid_name(command):
        return

    mapping: dict[str, Path] = {}
    initialize_sys_path()
    for path in odoo.addons.__path__:
        for fullpath in sorted(Path(path).glob(f"*/cli/{command}.py")):
            found_command = fullpath.stem
            if not Command.is_valid_name(found_command):
                continue
            fq_name = f"odoo.cli.{found_command}"
            if fq_name in mapping:
                _logger.warning(
                    "Addon CLI command %r is defined in multiple addons: "
                    "%s shadows %s (iteration order is not guaranteed)",
                    found_command,
                    fullpath,
                    mapping[fq_name],
                )
            mapping[fq_name] = fullpath

    for fq_name, fullpath in mapping.items():
        try:
            load_script(fullpath, fq_name)
        except ImportError as e:
            _logger.debug("Could not load CLI command %s: %s", fq_name, e)
        except Exception as e:
            _logger.warning("Failed to load CLI command %s: %s", fq_name, e)


def find_command(name: str) -> type[Command] | None:
    if not Command.is_valid_name(name):
        return None

    if name not in commands:
        expected_module = f"odoo.cli.{name}"
        try:
            __import__(expected_module)
        except ModuleNotFoundError as e:
            if e.name != expected_module:
                raise
        load_addons_commands(command=name)

    return commands.get(name)


def build_bootstrap_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--addons-path", default=None)
    return parser


def main() -> None:
    args = sys.argv[1:]

    boot_parser = build_bootstrap_parser()
    bootstrap, args = boot_parser.parse_known_args(args)
    odoo.cli.BOOTSTRAP_ADDONS_PATH = bootstrap.addons_path
    if bootstrap.addons_path is not None:
        config._parse_config([f"--addons-path={bootstrap.addons_path}"])

    if args and not args[0].startswith("-"):
        command_name = args[0]
        args = args[1:]
    elif args and args[0] in ("-h", "--help"):
        command_name = "help"
        args = args[1:]
    else:
        command_name = DEFAULT_COMMAND

    odoo.cli.COMMAND = command_name
    if command := find_command(command_name):
        command().run(args)
    else:
        sys.exit(
            f"Unknown command {command_name!r}.\n"
            f"Use '{PROG_NAME} --help' to see the list of available commands."
        )
