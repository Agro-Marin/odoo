"""odoo-bin command framework.

Entry point for ``odoo-bin <command> [args]``. :func:`main` discovers
:class:`Command` subclasses in ``odoo/cli/<name>.py`` (built-in) and
``<addon>/cli/<name>.py`` (addon-provided), importing each module only when
its command is dispatched.

Discovery contract: ``cli/<name>.py`` must define ``class <Name>(Command)``
whose lowercased name equals ``<name>``; set ``name`` explicitly when it would
not match (e.g. ``UpgradeCode`` sets ``name = "upgrade_code"``). Subclasses must
override ``run``; ``__init_subclass__`` enforces this at import, not dispatch.
"""

from .command import (
    Command,
    DatabaseCommand,
    build_config_args,
    get_single_database,
    main,
    odoo_env,
)

# Both set by main() before dispatch (None otherwise). COMMAND lets framework
# code (odoo.tests.common/.shell) gate behavior on the running subcommand.
# BOOTSTRAP_ADDONS_PATH is the raw --addons-path main() pulled from argv, so a
# command like `start` can tell whether the user passed one.
COMMAND: str | None = None
BOOTSTRAP_ADDONS_PATH: str | None = None
