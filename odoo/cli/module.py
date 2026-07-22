import argparse
import logging
import textwrap
import zipfile
from pathlib import Path
from typing import Any

from odoo.api import Environment
from odoo.modules.loading import force_demo
from odoo.modules.module import get_module_path, initialize_sys_path
from odoo.tools import OrderedSet, parse_version

from . import DatabaseCommand, odoo_env

_logger = logging.getLogger(__name__)


class Module(DatabaseCommand):
    """Manage modules, install demo data"""

    def __init__(self) -> None:
        super().__init__()
        subparsers = self.parser.add_subparsers(
            dest="subcommand", required=True, help="Subcommands help"
        )

        install_parser = subparsers.add_parser(
            "install",
            help="Install modules",
            description="Install selected modules",
        )
        install_parser.set_defaults(func=self._install)
        upgrade_parser = subparsers.add_parser(
            "upgrade",
            help="Upgrade modules",
            description="Upgrade selected modules",
        )
        upgrade_parser.set_defaults(func=self._upgrade)
        uninstall_parser = subparsers.add_parser(
            "uninstall",
            help="Uninstall modules",
            description="Uninstall selected modules",
        )
        uninstall_parser.set_defaults(func=self._uninstall)
        force_demo_parser = subparsers.add_parser(
            "force-demo",
            help="Install demo data (force)",
            description="Install demonstration data (force)",
        )
        force_demo_parser.set_defaults(func=self._force_demo)

        for parser in (
            install_parser,
            uninstall_parser,
            upgrade_parser,
            force_demo_parser,
        ):
            parser.formatter_class = argparse.RawDescriptionHelpFormatter
            self.add_config_arguments(parser)

        install_parser.add_argument(
            "modules",
            nargs="+",
            metavar="MODULE",
            help="names of the modules to be installed. For data modules (.zip), use the path instead",
        )
        install_parser.epilog = textwrap.dedent("""\
            Before installing modules, an Odoo database needs to be created and initialized
            on your PostgreSQL instance, using the `db init` command:

            $ odoo-bin db init <db_name>

            To get help on its parameters, see:

            $ odoo-bin db init --help
        """)
        uninstall_parser.add_argument(
            "modules",
            nargs="+",
            metavar="MODULE",
            help="names of the modules to be uninstalled",
        )
        upgrade_parser.add_argument(
            "modules",
            nargs="+",
            metavar="MODULE",
            help="name of the modules to be upgraded, use 'base' or 'all' if you want to upgrade everything",
        )
        upgrade_parser.add_argument(
            "--outdated",
            action="store_true",
            help="only update modules that have a newer version on disk. "
            "If 'all' is used as `modules` argument, this applies to all installed modules.",
        )

    def run(self, cmdargs: list[str]) -> None:
        parsed_args = self.parser.parse_args(args=cmdargs)
        self.bootstrap_config(parsed_args)
        parsed_args.func(parsed_args)

    def _get_zip_path(self, path: str) -> Path | None:
        fullpath = Path(path).resolve()
        # is_zipfile, not just the extension: the "not a readable .zip"
        # warning must be true, and _import_zipfile's traceback on a
        # mislabeled file is a worse failure mode than a clean warning.
        if (
            fullpath.is_file()
            and fullpath.suffix.lower() == ".zip"
            and zipfile.is_zipfile(fullpath)
        ):
            return fullpath
        return None

    def _get_module_names(self, module_names: list[str]) -> set[str]:
        """Return the module names that exist on disk (addon directory or .zip)."""
        initialize_sys_path()
        return {
            module
            for module in set(module_names)
            if get_module_path(module) or self._get_zip_path(module)
        }

    def _get_module_model(self, env: Environment) -> Any:
        Module = env["ir.module.module"]
        Module.update_list()
        return Module

    def _get_all_installed_modules(self, env: Environment) -> Any:
        return self._get_module_model(env).search([["state", "=", "installed"]])

    def _get_modules(self, env: Environment, module_names: set[str]) -> Any:
        return self._get_module_model(env).search([("name", "in", module_names)])

    def _install(self, parsed_args: argparse.Namespace) -> None:
        with odoo_env(parsed_args.db_name, new_registry=True) as env:
            valid_module_names = self._get_module_names(parsed_args.modules)
            installable_modules = self._get_modules(env, valid_module_names)
            if installable_modules:
                installable_modules.button_immediate_install()

            installed_names = set(installable_modules.mapped("name"))
            non_installable_modules = OrderedSet(
                module
                for module in parsed_args.modules
                if module not in installed_names
            )
            importable_zipfiles = [
                fullpath
                for module in non_installable_modules
                if (fullpath := self._get_zip_path(module))
            ]
            unknown_modules = [
                m for m in non_installable_modules if not self._get_zip_path(m)
            ]
            if unknown_modules:
                _logger.warning(
                    "Ignoring %d unrecognised module name(s) (not found on disk "
                    "and not a readable .zip): %s",
                    len(unknown_modules),
                    ", ".join(unknown_modules),
                )
            if importable_zipfiles:
                if "imported" not in env["ir.module.module"]._fields:
                    _logger.warning(
                        "Cannot import data modules unless the `base_import_module` module is installed"
                    )
                else:
                    for importable_zipfile in importable_zipfiles:
                        env["ir.module.module"]._import_zipfile(importable_zipfile)

    def _upgrade(self, parsed_args: argparse.Namespace) -> None:
        with odoo_env(parsed_args.db_name, new_registry=True) as env:
            if "all" in parsed_args.modules:
                upgradable_modules = self._get_all_installed_modules(env)
            else:
                valid_module_names = self._get_module_names(parsed_args.modules)
                upgradable_modules = self._get_modules(env, valid_module_names)
                # button_upgrade raises UserError for any not-installed module,
                # aborting the whole batch. Skip those with a warning so one bad
                # name doesn't poison the rest. (Also keeps --outdated meaningful:
                # uninstalled modules have db_version False, always "outdated".)
                if not_installed := upgradable_modules.filtered(
                    lambda m: m.state not in ("installed", "to upgrade")
                ):
                    _logger.warning(
                        "Skipping modules that are not installed: %s",
                        ", ".join(not_installed.mapped("name")),
                    )
                    upgradable_modules -= not_installed
            if parsed_args.outdated:
                upgradable_modules = upgradable_modules.filtered(
                    lambda x: (
                        parse_version(x.manifest_version) > parse_version(x.db_version)
                    ),
                )
            if upgradable_modules:
                upgradable_modules.button_immediate_upgrade()

    def _uninstall(self, parsed_args: argparse.Namespace) -> None:
        with odoo_env(parsed_args.db_name, new_registry=True) as env:
            modules = self._get_modules(env, parsed_args.modules)
            # install and upgrade both warn on typo'd names; a silent
            # uninstall "success" is worse — the user believes it happened.
            if unknown := set(parsed_args.modules) - set(modules.mapped("name")):
                _logger.warning(
                    "Ignoring unknown modules: %s", ", ".join(sorted(unknown))
                )
            if modules:
                modules.button_immediate_uninstall()

    def _force_demo(self, parsed_args: argparse.Namespace) -> None:
        with odoo_env(parsed_args.db_name, new_registry=True) as env:
            force_demo(env)
