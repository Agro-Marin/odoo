import os
import re
from pathlib import Path

import odoo.cli
from odoo.modules.module import MANIFEST_NAMES, Manifest
from odoo.tools import config

from . import Command
from .server import main


class Start(Command):
    """Quickly start the odoo server with default options"""

    def get_module_list(self, path: str | Path) -> list[str]:
        """Return module names found under ``path``."""
        base = Path(path)
        return [
            match.parent.name
            for mname in MANIFEST_NAMES
            for match in base.glob(f"*/{mname}")
        ]

    def __init__(self) -> None:
        super().__init__()
        self.parser.add_argument(
            "-p",
            "--path",
            default=None,
            help="Directory where your project's modules are stored "
            "(default: current directory, or $VIRTUAL_ENV when set). "
            "NOTE: `-p` is --path here, not the server's --http-port",
        )
        self.parser.add_argument(
            "-d",
            "--database",
            dest="db_name",
            default=None,
            help="database name (default: db_name from the config file, else "
            "the project directory name)",
        )

    def run(self, cmdargs: list[str]) -> None:
        config.parser.prog = self.prog
        args, _unknown = self.parser.parse_known_args(args=cmdargs)

        # Strip start's own flags before anything hands argv to the server's
        # config parser, which does not know them.
        server_args = [v for i, v in enumerate(cmdargs) if not _is_path_arg(i, cmdargs)]

        # Resolve the configuration BEFORE creating a database. `db_host`,
        # `db_port`, `db_user`, `db_sslmode` and `db_template` all decide what
        # "create this database" means, and `refuse_maintenance_db` cannot know
        # the configured template until the file has been read. This ran after
        # creation until 2026-08: `start -c prod.conf` created the database on
        # whatever PGHOST happened to be set, then served from the configured
        # one, and the template guard compared against `template0` whatever the
        # config said.
        config._parse_config(server_args)

        project_path, db_name = self._resolve_project(args.path, args.db_name)

        mods = self.get_module_list(project_path)
        if mods and not _has_arg(server_args, "--addons-path"):
            addons_paths = [str(project_path)]
            if bootstrap_value := odoo.cli.BOOTSTRAP_ADDONS_PATH:
                user_paths = [p for p in bootstrap_value.split(",") if p]
                addons_paths = user_paths + [
                    p for p in addons_paths if p not in user_paths
                ]
            server_args.append(f"--addons-path={','.join(addons_paths)}")

        if not args.db_name:
            server_args.extend(("-d", db_name))

        # Creating the database, refusing a system/template one and marking
        # `base` for installation are NOT done here: `server.main` already does
        # all three, once it has parsed the configuration. This command used to
        # carry its own copy that ran *before* the parse, and the copy was both
        # wrong and silently ineffective — `config["init"]["base"] = True` was
        # discarded by `main`'s own `parse_config`, whose `_postprocess_options`
        # rebuilds `_runtime_options["init"]` from the CLI/file/env options. The
        # database `start` had just created was then served uninitialized:
        # "Database X not initialized, skipping (use `-i base` to bootstrap)",
        # which is the whole of what `start` promises.
        if not _has_arg(server_args, "--db-filter"):
            server_args.append(f"--db-filter=^{re.escape(db_name)}$")

        main(server_args)

    def _resolve_project(
        self, path: str | None, explicit_db_name: str | None
    ) -> tuple[Path, str]:
        """Resolve the addons directory and the database name.

        A ``--path`` that is not a directory is a usage error rather than a
        database name to invent one from: ``-p`` is ``--path`` here while it is
        ``--http-port`` for every other command, so ``start -p 8070`` used to
        create a database called ``8070`` and serve on the default port.

        Name precedence, most explicit source first: ``-d``, then the module
        directory when the path points inside one, then the config file's
        ``db_name``, then the project directory. The config file used to lose
        to the directory name, so ``start -c prod.conf`` served a database
        named after the cwd rather than the one it configured.
        """
        if path is None:
            path = os.environ.get("VIRTUAL_ENV") or "."
        project_path = Path(os.path.expandvars(path)).expanduser().resolve()
        if not project_path.is_dir():
            hint = (
                " (`-p` is --path here; the server's port option is --http-port)"
                if str(path).isdigit()
                else ""
            )
            self.parser.error(f"--path {path!r} is not a directory{hint}")

        db_name = None
        if is_path_in_module(project_path):
            db_name = project_path.name
            project_path = project_path.parent.resolve()

        configured = config["db_name"]
        db_name = (
            explicit_db_name
            or db_name
            or (configured[0] if configured and len(configured) == 1 else None)
            or project_path.name
        )
        return project_path, db_name


def is_path_in_module(path: str | Path) -> bool:
    """Check if ``path`` is inside an Odoo module directory."""
    path = Path(path)
    return any(Manifest._from_path(p) for p in (path, *path.parents))


def _is_path_arg(index: int, args: list[str]) -> bool:
    """Return True when ``args[index]`` belongs to start's own ``--path``."""
    arg = args[index]
    if arg == "--path" or arg.startswith(("--path=", "-p")):
        return True
    return index > 0 and args[index - 1] in ("-p", "--path")


def _has_arg(cmdargs: list[str], name: str) -> bool:
    """Return True if ``name`` is present in ``cmdargs`` in either ``--name``
    or ``--name=value`` form."""
    return any(arg == name or arg.startswith(f"{name}=") for arg in cmdargs)
