"""odoo-bin command framework.

Entry point for ``odoo-bin <command> [args]``. The dispatcher discovers
:class:`Command` subclasses declared in:

* ``odoo/cli/<name>.py`` — built-in commands
* ``<addon>/cli/<name>.py`` — addon-provided commands

Only the dispatch machinery (``Command``, ``main``, helpers) is eagerly
imported here; individual command modules are loaded lazily by
:func:`main` so ``odoo-bin --help`` pays a minimal startup cost.

Discovery contract
------------------
A file at ``cli/<name>.py`` must define ``class <Name>(Command)`` whose
lowercased class name equals ``<name>``. Set ``cls.name`` explicitly when
the lowercased class name would not match the module name (e.g.
``UpgradeCode`` sets ``name = "upgrade_code"``).

Every subclass must override ``run(self, args: list[str]) -> None``. The
check runs at class-definition time via ``__init_subclass__`` so a
missing override fails fast rather than dispatching to a silent no-op.

Example
-------
::

    # addons/my_addon/cli/greet.py
    from odoo.cli import Command

    class Greet(Command):
        \"\"\"Print a greeting\"\"\"

        def run(self, args):
            self.parser.add_argument("name")
            parsed = self.parser.parse_args(args)
            print(f"Hello, {parsed.name}!")

Then: ``odoo-bin greet world``.

Public API
----------
* :class:`Command` — base class to subclass for new commands
* :func:`main` — ``odoo-bin`` dispatcher entry point
* :func:`build_config_args` — shape ``-c`` / ``-d`` for ``config.parse_config``
* :func:`get_single_database` — validate the config supplies exactly one db
* :func:`odoo_env` — context manager yielding an ``odoo.api.Environment``

:data:`COMMAND` is set to the resolved command name while ``main()``
runs (``None`` otherwise). Framework components read it to gate behavior
on which subcommand is executing — see ``odoo.tests.common`` and
``odoo.tests.shell``.
"""

from .command import (
    Command,
    build_config_args,
    get_single_database,
    main,
    odoo_env,
)

# Set by main() before dispatch; see module docstring for consumers.
COMMAND: str | None = None
