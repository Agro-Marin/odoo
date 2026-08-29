import os
import re
from pathlib import Path

import odoo.cli
from odoo.modules.module import MANIFEST_NAMES, Manifest
from odoo.tools import config

from . import Command
from .server import main


class Start(Command):
    description = "Quickly start the odoo server with default options"

    def get_module_list(self, path: str | Path) -> list[str]:
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

        server_args = [v for i, v in enumerate(cmdargs) if not _is_path_arg(i, cmdargs)]

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

        if not _has_arg(server_args, "--db-filter"):
            server_args.append(f"--db-filter=^{re.escape(db_name)}$")

        main(server_args)

    def _resolve_project(
        self, path: str | None, explicit_db_name: str | None
    ) -> tuple[Path, str]:
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
    path = Path(path)
    return any(Manifest._from_path(str(p)) for p in (path, *path.parents))


def _is_path_arg(index: int, args: list[str]) -> bool:
    arg = args[index]
    if arg == "--path" or arg.startswith(("--path=", "-p")):
        return True
    return index > 0 and args[index - 1] in ("-p", "--path")


def _has_arg(cmdargs: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for arg in cmdargs)
