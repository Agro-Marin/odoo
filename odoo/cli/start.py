import os
import re
import sys
from pathlib import Path

import odoo.cli
from odoo.db import is_maintenance_db
from odoo.modules.module import MANIFEST_NAMES, Manifest
from odoo.service.db import DatabaseExists, _create_empty_database
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

    def run(self, cmdargs: list[str]) -> None:
        config.parser.prog = self.prog
        self.parser.add_argument(
            "-p",
            "--path",
            default=None,
            help="Directory where your project's modules are stored "
            "(default: current directory, or $VIRTUAL_ENV when set)",
        )
        self.parser.add_argument(
            "-d",
            "--database",
            dest="db_name",
            default=None,
            help="database name (default: project directory name)",
        )

        args, _unknown = self.parser.parse_known_args(args=cmdargs)

        if args.path is None:
            args.path = os.environ.get("VIRTUAL_ENV") or "."
        project_path = Path(os.path.expandvars(args.path)).expanduser().resolve()
        db_name = None
        if is_path_in_module(project_path):
            db_name = project_path.name
            project_path = project_path.parent.resolve()

        mods = self.get_module_list(project_path)
        if mods and not _has_arg(cmdargs, "--addons-path"):
            addons_paths = [str(project_path)]
            if bootstrap_value := odoo.cli.BOOTSTRAP_ADDONS_PATH:
                user_paths = [p for p in bootstrap_value.split(",") if p]
                addons_paths = user_paths + [
                    p for p in addons_paths if p not in user_paths
                ]
            cmdargs.append(f"--addons-path={','.join(addons_paths)}")

        if not args.db_name:
            args.db_name = db_name or project_path.name
            cmdargs.extend(("-d", args.db_name))

        if is_maintenance_db(args.db_name):
            sys.exit(
                f"Refusing to use system or template database `{args.db_name}`; "
                "pass -d to choose another database name."
            )
        try:
            _create_empty_database(args.db_name)
            config["init"]["base"] = True
        except DatabaseExists:
            pass
        except Exception as e:
            sys.exit(f"Could not create database `{args.db_name}`. ({e})")

        if not _has_arg(cmdargs, "--db-filter"):
            cmdargs.append(f"--db-filter=^{re.escape(args.db_name)}$")

        def is_path_arg(index: int, args: list[str]) -> bool:
            arg = args[index]
            if arg == "--path" or arg.startswith(("--path=", "-p")):
                return True
            return index > 0 and args[index - 1] in ("-p", "--path")

        cmdargs = [v for i, v in enumerate(cmdargs) if not is_path_arg(i, cmdargs)]

        main(cmdargs)


def is_path_in_module(path: str | Path) -> bool:
    """Check if ``path`` is inside an Odoo module directory."""
    path = Path(path)
    return any(Manifest._from_path(p) for p in (path, *path.parents))


def _has_arg(cmdargs: list[str], name: str) -> bool:
    """Return True if ``name`` is present in ``cmdargs`` in either ``--name``
    or ``--name=value`` form."""
    return any(arg == name or arg.startswith(f"{name}=") for arg in cmdargs)
