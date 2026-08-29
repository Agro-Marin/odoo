from .command import (
    Command,
    DatabaseCommand,
    build_config_args,
    get_single_database,
    main,
    odoo_env,
)

COMMAND: str | None = None
BOOTSTRAP_ADDONS_PATH: str | None = None
