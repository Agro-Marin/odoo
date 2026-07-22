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

# \Z (not $): $ also matches before a trailing newline, so a name like
# 'db\n' would be accepted and travel into the import machinery.
COMMAND_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\Z")
PROG_NAME = Path(sys.argv[0]).name
DEFAULT_COMMAND = "server"
"""Command dispatched when argv names none; also rendered by ``help``."""
commands: dict[str, type[Command]] = {}
"""All loaded commands"""


def build_config_args(
    config_file: str | None = None,
    db_name: str | None = None,
    *,
    no_http: bool = True,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build an argument list for ``config.parse_config()`` from a config file
    (``-c``), a database name (``-d``), ``--no-http``, and any extra args."""
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
    """Validate and return the single configured database name.

    Refuses the PostgreSQL system databases and the configured creation
    template: opening a registry on one of them would initialize Odoo tables
    inside it (``load_modules`` bootstraps any uninitialized database),
    corrupting cluster infrastructure. Every caller parses the config before
    calling, so ``config['db_template']`` is resolved.

    :param db_names: candidate names, typically ``config['db_name']``
    :param allow_none: return None instead of erroring when none is given
    :param error_handler: called with the message on failure; defaults to
        ``sys.exit``. Pass ``self.parser.error`` for argparse integration.
    """
    if error_handler is None:
        error_handler = sys.exit

    if not db_names:
        if allow_none:
            return None
        error_handler(
            "No database specified. Use -d/--database or set db_name in the config file."
        )
        # Guard the fall-through for a handler that returns (not NoReturn).
        return None

    if len(db_names) > 1:
        error_handler(
            f"Multiple databases configured ({db_names}); "
            "please provide a single one via -d/--database."
        )
        return None

    db_name = db_names[0]
    # Lazy import: odoo.service pulls psycopg and the api layer; the
    # dispatcher must stay cheap to start (same policy as odoo_env below).
    from odoo.service._db_helpers import SYSTEM_DBS

    if db_name in SYSTEM_DBS or db_name == config["db_template"]:
        error_handler(f"Refusing to use system or template database {db_name}.")
        return None

    return db_name


@contextlib.contextmanager
def odoo_env(
    db_name: str,
    *,
    readonly: bool = False,
    context: dict | None = None,
    uid: int | None = None,
    new_registry: bool = False,
) -> Generator:
    """Yield an Odoo :class:`Environment` for ``db_name``, closing the cursor on exit.

    :param readonly: open a readonly cursor (no writes allowed)
    :param context: environment context (default ``{}``)
    :param uid: acting user (default ``SUPERUSER_ID``)
    :param new_registry: build a fresh registry via ``Registry.new()``
    """
    # Lazy imports to keep startup cheap.
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
        # Built lazily by the `parser` property. Not cached_property, so a
        # subclass can build it eagerly in __init__ (e.g. to add subparsers).
        self._parser: argparse.ArgumentParser | None = None

    def run(self, args: list[str]) -> None:
        """Execute the command with ``args`` (the tokens after the command name).

        Subclasses MUST override this; the base raises so a missing override
        fails fast instead of registering a no-op command.
        """
        raise NotImplementedError(
            f"{type(self).__qualname__} must override `run(self, args)`"
        )

    def __init_subclass__(cls, register: bool = True) -> None:
        """Validate and register the command subclass.

        :param bool register: pass ``False`` for abstract helper bases
            (e.g. ``class DatabaseCommand(Command, register=False)``) that
            share behavior between commands. Unregistered bases skip the
            name/module and ``run``-override checks; their concrete
            subclasses are validated and registered as usual.
        """
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
        # Catch a missing override at import, not first run. An inherited
        # override (Leaf <- Mid) is Mid.run, not Command.run, so it passes.
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
    """Base for commands that operate on a single configured database.

    Feeds the parsed ``-c``/``-d`` into the global config, then checks that
    exactly one database is targeted. Subclasses add the flags themselves (via
    :meth:`add_config_arguments`): flag placement — main parser vs. subparser —
    is a per-command layout decision. Kept off :class:`Command` since db-free
    commands (``deploy``, ``scaffold``, ``help``) don't need it.
    """

    def add_config_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add the standard ``-c``/``--config`` and ``-d``/``--database``
        arguments to ``parser`` (a main parser or a subparser).
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
        parser.add_argument(
            "-D",
            "--data-dir",
            dest="data_dir",
            default=None,
            help="directory where to store Odoo data",
        )

    def bootstrap_config(
        self,
        parsed_args: argparse.Namespace,
        *,
        allow_none: bool = False,
    ) -> str | None:
        """Parse config from ``parsed_args`` and return the database name.

        :param parsed_args: namespace holding ``config`` and ``db_name``
            (as produced by ``add_config_arguments``)
        :param bool allow_none: when True, a missing database returns None
            instead of exiting
        :return: the single validated database name (also written back to
            ``parsed_args.db_name``)
        """
        extra_args = None
        if getattr(parsed_args, "data_dir", None):
            # let a platform enforce --data-dir even when the config file is
            # user-controlled (the odoorc file remains the preferred way)
            extra_args = ["-D", parsed_args.data_dir]
        config_args = build_config_args(
            parsed_args.config, parsed_args.db_name, extra_args=extra_args
        )
        config.parse_config(config_args, setup_logging=True)
        return self.require_single_database(parsed_args, allow_none=allow_none)

    def require_single_database(
        self,
        parsed_args: argparse.Namespace,
        *,
        allow_none: bool = False,
    ) -> str | None:
        """Validate that exactly one database is configured and return it.

        Wraps :func:`get_single_database`, routing errors through
        ``self.parser.error`` (argparse program name + exit code) and writing
        the resolved name back onto ``parsed_args.db_name``.

        :param allow_none: when True, a missing database returns None
        :raises SystemExit: via ``parser.error()`` if validation fails
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
            found_command = fullpath.stem
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
            # Optional-dependency failures are recoverable; debug-log only.
            _logger.debug("Could not load CLI command %s: %s", fq_name, e)
        except Exception as e:
            # `odoo-bin help` loads every addon's cli/*.py; one broken file
            # must not break discovery for all. Warn and keep going.
            _logger.warning("Failed to load CLI command %s: %s", fq_name, e)


def find_command(name: str) -> type[Command] | None:
    """Get command by name."""

    # Reject invalid names early: a dotted name like 'db.init' would raise
    # ModuleNotFoundError for a *parent* module, which the guard below refuses
    # to swallow — surfacing a traceback for what is just an unknown command.
    if not Command.is_valid_name(name):
        return None

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


def build_bootstrap_parser() -> argparse.ArgumentParser:
    """Build the pre-dispatch parser that extracts ``--addons-path``.

    ``allow_abbrev=False`` is load-bearing: otherwise any unambiguous prefix
    (``--addons``, ``--add``, ``--a``) would be consumed as the addons path
    before the command sees it. A standalone factory so it can be unit tested.
    """
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--addons-path", default=None)
    return parser


def main() -> None:
    args = sys.argv[1:]

    # Extract --addons-path before dispatch so addon commands are discoverable
    # (e.g. for --help); accepts both `=PATH` and ` PATH` forms in any position.
    # Use the private _parse_config: the public parse_config flushes warnings to
    # stderr, breaking test_unknown_command's exact-stderr assertion.
    boot_parser = build_bootstrap_parser()
    bootstrap, args = boot_parser.parse_known_args(args)
    # Record the raw value (None when absent); the flag is gone from `args`.
    odoo.cli.BOOTSTRAP_ADDONS_PATH = bootstrap.addons_path
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
        command_name = DEFAULT_COMMAND

    # Set before find_command: importing a command module can transitively read
    # COMMAND at import time (odoo.tests.common); setting it later would show None.
    odoo.cli.COMMAND = command_name
    if command := find_command(command_name):
        command().run(args)
    else:
        sys.exit(
            f"Unknown command {command_name!r}.\n"
            f"Use '{PROG_NAME} --help' to see the list of available commands."
        )
