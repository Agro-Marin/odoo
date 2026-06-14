import os
import re
import sys
from pathlib import Path

import odoo.cli
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
        # default=None, not ".": an explicit `-p .` must win over the
        # $VIRTUAL_ENV fallback below, which only applies when the flag
        # was omitted.
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
            help="Specify the database name (default to project's directory name",
        )

        args, _unknown = self.parser.parse_known_args(args=cmdargs)

        # When in a virtualenv, by default use its path rather than the cwd
        if args.path is None:
            args.path = os.environ.get("VIRTUAL_ENV") or "."
        project_path = Path(os.path.expandvars(args.path)).expanduser().resolve()
        db_name = None
        if is_path_in_module(project_path):
            # started in a module so we choose this module name for database
            db_name = project_path.name
            # go to the parent's directory of the module root
            project_path = project_path.parent.resolve()

        # check if one of the subfolders has at least one module
        mods = self.get_module_list(project_path)
        if mods and not _has_arg(cmdargs, "--addons-path"):
            # The dispatcher's bootstrap parser consumes --addons-path from
            # any argv position, so a user-supplied path never appears in
            # cmdargs (_has_arg above only covers direct invocations that
            # bypass main()). Appending the bare project path here would
            # make the second config parse *replace* the user's value —
            # merge instead, user paths first.
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

        # TODO: forbid some database names ? eg template1, ...
        try:
            _create_empty_database(args.db_name)
            config["init"]["base"] = True
        except DatabaseExists:
            pass
        except Exception as e:
            sys.exit(f"Could not create database `{args.db_name}`. ({e})")

        if not _has_arg(cmdargs, "--db-filter"):
            # re.escape prevents regex meta-chars in db_name ('.', '-', '+')
            # from matching unrelated databases.
            cmdargs.append(f"--db-filter=^{re.escape(args.db_name)}$")

        # Remove --path /-p options from the command arguments
        def is_path_arg(index: int, args: list[str]) -> bool:
            arg = args[index]
            # `-p`/`--path` with a separate value, `--path=X`, and the
            # concatenated short form `-pX` that argparse also accepts.
            # Leaking `-pX` is worse than a parse error: the server parser
            # maps `-p` to --http-port, so a numeric path would silently
            # change the listening port.
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
