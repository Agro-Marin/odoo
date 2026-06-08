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
import odoo.init  # noqa: F401 — side-effect import: Python version check + GC tuning
from odoo.modules import initialize_sys_path, load_script
from odoo.tools import config

_logger = logging.getLogger(__name__)

COMMAND_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PROG_NAME = Path(sys.argv[0]).name
commands: dict[str, type] = {}
"""All loaded commands"""


def build_config_args(
    config_file: str | None = None,
    db_name: str | None = None,
    *,
    no_http: bool = True,
    extra_args: list[str] | None = None,
) -> list[str]:
    """
    Build argument list for config.parse_config().

    Args:
        config_file: Path to configuration file (-c)
        db_name: Database name (-d)
        no_http: Include --no-http flag (default True)
        extra_args: Additional arguments to append

    Returns:
        List of arguments ready for config.parse_config()
    """
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
    """
    Validate and return a single database name from config.

    Args:
        db_names: List of database names (typically from config['db_name'])
        allow_none: If True, returns None when no database provided
        error_handler: Callable for error messages. Defaults to sys.exit().
                      For argparse integration, pass self.parser.error

    Returns:
        Single database name, or None if allow_none=True and no db provided

    Raises:
        SystemExit (via error_handler) if validation fails
    """
    if error_handler is None:
        error_handler = sys.exit

    if not db_names:
        if allow_none:
            return None
        error_handler(
            "No database specified. Use -d/--database or set db_name in the config file."
        )
        # Defensive: if a caller supplied a non-NoReturn handler, do not
        # fall through into the len(None) branch below.
        return None

    if len(db_names) > 1:
        error_handler(
            f"Multiple databases configured ({db_names}); "
            "please provide a single one via -d/--database."
        )
        return None

    return db_names[0]


@contextlib.contextmanager
def odoo_env(
    db_name: str,
    *,
    readonly: bool = False,
    context: dict | None = None,
    uid: int | None = None,
    new_registry: bool = False,
) -> Generator:
    """
    Context manager for creating an Odoo Environment with proper cleanup.

    Args:
        db_name: Database name
        readonly: If True, use readonly cursor (no writes allowed)
        context: Custom context dict, defaults to {}
        uid: User ID, defaults to SUPERUSER_ID
        new_registry: If True, use Registry.new() instead of Registry()

    Yields:
        Odoo Environment instance

    Example:
        with odoo_env('mydb', readonly=True) as env:
            partners = env['res.partner'].search([])
    """
    # Lazy imports to maintain startup performance
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
    """Base class for odoo-bin commands.

    Subclasses MUST live in a module whose name matches `cls.name` (or, if
    `name` is left as None, the lowercased class name). For class names that
    don't auto-snake-case correctly (e.g. ``UpgradeCode`` for module
    ``upgrade_code``) set ``name`` explicitly at class scope.
    """

    name: str | None = None
    description: str | None = None
    epilog: str | None = None

    def __init__(self) -> None:
        # Lazy-init; the property below builds the parser on first access. We
        # do NOT use cached_property so subclasses can opt to build the parser
        # eagerly in their own __init__ (e.g. when adding subparsers).
        self._parser: argparse.ArgumentParser | None = None

    def run(self, args: list[str]) -> None:
        """Execute the command with ``args`` (the tokens after the command name).

        Subclasses MUST override this. The base implementation raises so that
        a class that inadvertently relies on inheritance-without-override
        fails fast rather than being registered as a no-op command.
        """
        raise NotImplementedError(
            f"{type(self).__qualname__} must override `run(self, args)`"
        )

    def __init_subclass__(cls) -> None:
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
        # Identity check against Command.run catches a missing override at
        # class-definition time (import), not at dispatch time (first run).
        # Works transitively: if MidCommand overrides and LeafCommand(MidCommand)
        # does not, LeafCommand.run is MidCommand.run, not Command.run, so
        # we correctly accept the inherited-valid-override case.
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

    def add_config_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Add standard -c/--config and -d/--database arguments to parser.

        Args:
            parser: ArgumentParser or subparser to add arguments to
        """
        parser.add_argument(
            "-c",
            "--config",
            dest="config",
            help="use a specific configuration file",
        )
        parser.add_argument(
            "-d",
            "--database",
            dest="db_name",
            default=None,
            help="database name, connection details will be taken from the config file",
        )

    def require_single_database(
        self,
        parsed_args: argparse.Namespace,
        *,
        allow_none: bool = False,
    ) -> str | None:
        """
        Validate single database and update parsed_args.db_name.

        Thin wrapper over ``get_single_database`` that (a) routes errors
        through ``self.parser.error`` so they pick up the argparse program
        name and exit code, and (b) writes the resolved name back onto the
        parsed namespace for convenience.

        Args:
            parsed_args: Namespace from argument parsing
            allow_none: If True, returns None when no database configured

        Returns:
            Database name (also set on parsed_args.db_name)

        Raises:
            SystemExit via parser.error() if validation fails
        """
        db_name = get_single_database(
            config["db_name"],
            allow_none=allow_none,
            error_handler=self.parser.error,
        )
        if db_name is not None:
            parsed_args.db_name = db_name
        return db_name


def load_internal_commands() -> None:
    """Load ``commands`` from ``odoo.cli``"""
    for path in odoo.cli.__path__:
        for module in Path(path).iterdir():
            if module.suffix != ".py" or module.stem.startswith("_"):
                continue
            __import__(f"odoo.cli.{module.stem}")


def load_addons_commands(command: str | None = None) -> None:
    """
    Search the addons path for modules with a ``cli/{command}.py`` file.
    In case no command is provided, discover and load all the commands.
    """
    if command is None:
        command = "*"
    elif not Command.is_valid_name(command):
        return

    mapping: dict[str, Path] = {}
    initialize_sys_path()
    for path in odoo.addons.__path__:
        for fullpath in Path(path).glob(f"*/cli/{command}.py"):
            if not (found_command := fullpath.stem):
                continue
            if not Command.is_valid_name(found_command):
                continue
            # loading as odoo.cli and not odoo.addons.{module}.cli
            # so it doesn't load odoo.addons.{module}.__init__
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
            # Addon CLI scripts may import optional dependencies; skip silently
            # but record at debug level so the failure is recoverable.
            _logger.debug("Could not load CLI command %s: %s", fq_name, e)


def find_command(name: str) -> type[Command] | None:
    """Get command by name."""

    # built-in commands
    if command := commands.get(name):
        return command

    # import from odoo.cli — suppress ONLY "this module doesn't exist", not
    # ImportError raised from inside an existing command module.
    expected_module = f"odoo.cli.{name}"
    try:
        __import__(expected_module)
    except ModuleNotFoundError as e:
        if e.name != expected_module:
            raise
    else:
        if name in commands:
            return commands[name]

    # import from odoo.addons.*.cli
    load_addons_commands(command=name)
    return commands.get(name)


def main() -> None:
    args = sys.argv[1:]

    # Bootstrap: extract --addons-path before the command is dispatched, so that
    # addon-provided CLI commands are discoverable (e.g. for `--help`). Accepts
    # both `--addons-path=PATH` and `--addons-path PATH` forms in any position.
    # We call the private `_parse_config` (rather than the public `parse_config`)
    # because the latter flushes config warnings to stderr — that breaks the
    # contract of `test_unknown_command` which asserts an exact stderr message.
    boot_parser = argparse.ArgumentParser(add_help=False)
    boot_parser.add_argument("--addons-path", default=None)
    bootstrap, args = boot_parser.parse_known_args(args)
    if bootstrap.addons_path is not None:
        config._parse_config([f"--addons-path={bootstrap.addons_path}"])

    if args and not args[0].startswith("-"):
        # Command specified, search for it
        command_name = args[0]
        args = args[1:]
    elif "-h" in args or "--help" in args:
        # No command specified, but help is requested
        command_name = "help"
        args = [x for x in args if x not in ("-h", "--help")]
    else:
        # No command specified, default command used
        command_name = "server"

    if command := find_command(command_name):
        odoo.cli.COMMAND = command_name
        command().run(args)
    else:
        sys.exit(
            f"Unknown command {command_name!r}.\n"
            f"Use '{PROG_NAME} --help' to see the list of available commands."
        )
