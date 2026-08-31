from .command import (
    Command,
    DatabaseCommand,
    get_config_argv,
    get_single_database,
    main,
    odoo_env,
)

COMMAND: str | None = None
BOOTSTRAP_ADDONS_PATH: str | None = None
