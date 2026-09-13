import argparse
import functools
import logging
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any, NoReturn

from odoo.api import Environment
from odoo.libs.debug_log import DebugLog
from odoo.modules.loading import force_demo
from odoo.modules.module import get_module_path, initialize_sys_path
from odoo.tools import OrderedSet, parse_version

from . import DatabaseCommand, open_environment

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)


def _exit_nothing_done(verb: str, requested: list[str] | set[str]) -> NoReturn:
    _debug.logic("cli.module.nothing_done", verb=verb, requested=len(requested))
    sys.exit(
        f"Nothing to {verb}: none of the requested modules "
        f"({', '.join(sorted(requested))}) could be resolved."
    )


class Module(DatabaseCommand):
    description = "Manage modules, install demo data"

    def __init__(self) -> None:
        super().__init__()
        self.add_config_arguments(self.parser)
        subparsers = self.parser.add_subparsers(
            dest="subcommand", required=True, help="Subcommands help"
        )

        install_parser = subparsers.add_parser(
            "install",
            help="Install modules",
            description="Install selected modules",
        )
        install_parser.set_defaults(func=self._install_modules)
        upgrade_parser = subparsers.add_parser(
            "upgrade",
            help="Upgrade modules",
            description="Upgrade selected modules",
        )
        upgrade_parser.set_defaults(func=self._upgrade_modules)
        uninstall_parser = subparsers.add_parser(
            "uninstall",
            help="Uninstall modules",
            description="Uninstall selected modules",
        )
        uninstall_parser.set_defaults(func=self._uninstall_modules)
        force_demo_parser = subparsers.add_parser(
            "force-demo",
            help="Install demo data (force)",
            description="Install demonstration data (force)",
        )
        force_demo_parser.set_defaults(func=self._force_demo_data)

        for parser in (
            install_parser,
            uninstall_parser,
            upgrade_parser,
            force_demo_parser,
        ):
            parser.formatter_class = argparse.RawDescriptionHelpFormatter
            self.add_config_arguments(parser, on_subparser=True)

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
        parsed_args, unknown = self.parse_args(cmdargs)
        self.bootstrap_config(parsed_args, extra_args=unknown)
        subcommand = getattr(parsed_args.func, "__name__", None)
        _debug.lifecycle(
            "cli.module",
            subcommand=subcommand,
            db=parsed_args.db_name,
            modules=len(getattr(parsed_args, "modules", ())),
        )
        parsed_args.func(parsed_args)
        _debug.lifecycle("cli.module.done", subcommand=subcommand)

    @staticmethod
    @functools.cache
    def _get_zip_path(path: str) -> Path | None:
        fullpath = Path(path).resolve()
        if (
            fullpath.is_file()
            and fullpath.suffix.lower() == ".zip"
            and zipfile.is_zipfile(fullpath)
        ):
            _debug.logic("cli.module.zip_resolved", path=path, zip=True)
            return fullpath
        _debug.logic("cli.module.zip_resolved", path=path, zip=False)
        return None

    def _get_module_names_on_disk(self, module_names: list[str]) -> set[str]:
        initialize_sys_path()
        found = {
            module
            for module in set(module_names)
            if get_module_path(module) or self._get_zip_path(module)
        }
        _debug.logic(
            "cli.module.on_disk", requested=len(set(module_names)), found=len(found)
        )
        return found

    @staticmethod
    def _split_installed(modules: Any) -> tuple[Any, Any]:
        already_installed = modules.filtered(lambda m: m.state == "installed")
        return already_installed, modules - already_installed

    def _sync_module_list(self, env: Environment) -> Any:
        Module = env["ir.module.module"]
        with _debug.perf("cli.module.update_list", cr=env.cr) as span:
            result = Module.update_list()
            span.set(
                updated=getattr(result, "updated", None),
                added=getattr(result, "added", None),
            )
        return Module

    def _get_modules_installed(self, env: Environment) -> Any:
        installed = self._sync_module_list(env).search([["state", "=", "installed"]])
        _debug.logic("cli.module.installed_set", count=len(installed))
        return installed

    def _get_modules_named(self, env: Environment, module_names: set[str]) -> Any:
        modules = self._sync_module_list(env).search([("name", "in", module_names)])
        _debug.logic(
            "cli.module.named_set", requested=len(module_names), found=len(modules)
        )
        return modules

    def _install_modules(self, parsed_args: argparse.Namespace) -> None:
        with open_environment(parsed_args.db_name, new_registry=True) as env:
            valid_module_names = self._get_module_names_on_disk(parsed_args.modules)
            installable_modules = self._get_modules_named(env, valid_module_names)
            already_installed, to_install = self._split_installed(installable_modules)
            _debug.pipeline(
                "cli.module.install",
                db=parsed_args.db_name,
                requested=len(parsed_args.modules),
                on_disk=len(valid_module_names),
                installable=len(installable_modules),
                already_installed=len(already_installed),
                to_install=len(to_install),
            )
            if already_installed:
                _logger.info(
                    "Already installed, nothing to do for: %s",
                    ", ".join(already_installed.mapped("name")),
                )
            if to_install:
                with _debug.perf(
                    "cli.module.install_run", cr=env.cr, modules=len(to_install)
                ):
                    to_install.button_immediate_install()
                _debug.lifecycle(
                    "cli.module.installed",
                    db=parsed_args.db_name,
                    modules=len(to_install),
                )

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
            _debug.logic(
                "cli.module.install_leftovers",
                zips=len(importable_zipfiles),
                unknown=len(unknown_modules),
            )
            if unknown_modules:
                _logger.warning(
                    "Ignoring %d unrecognised module name(s) (not found on disk "
                    "and not a readable .zip): %s",
                    len(unknown_modules),
                    ", ".join(unknown_modules),
                )
            if not installable_modules and not importable_zipfiles:
                _exit_nothing_done("install", unknown_modules)
            if importable_zipfiles:
                if "imported" not in env["ir.module.module"]._fields:
                    _debug.logic(
                        "cli.module.import_zip_refused", reason="no_base_import_module"
                    )
                    sys.exit(
                        f"Cannot import {len(importable_zipfiles)} data "
                        "module(s): the `base_import_module` module is not "
                        "installed in this database."
                    )
                for importable_zipfile in importable_zipfiles:
                    with _debug.perf(
                        "cli.module.import_zip", cr=env.cr, path=str(importable_zipfile)
                    ):
                        env["ir.module.module"]._import_zipfile(importable_zipfile)
                    _debug.lifecycle(
                        "cli.module.zip_imported",
                        db=parsed_args.db_name,
                        path=str(importable_zipfile),
                    )

    def _upgrade_modules(self, parsed_args: argparse.Namespace) -> None:
        with open_environment(parsed_args.db_name, new_registry=True) as env:
            if "all" in parsed_args.modules:
                _debug.logic("cli.module.upgrade_scope", scope="all")
                upgradable_modules = self._get_modules_installed(env)
            else:
                valid_module_names = self._get_module_names_on_disk(parsed_args.modules)
                if unknown := set(parsed_args.modules) - valid_module_names:
                    _debug.logic(
                        "cli.module.modules_skipped",
                        verb="upgrade",
                        reason="not_on_disk",
                        count=len(unknown),
                    )
                    _logger.warning(
                        "Ignoring modules not found on disk: %s",
                        ", ".join(sorted(unknown)),
                    )
                upgradable_modules = self._get_modules_named(env, valid_module_names)
                if unknown_in_db := valid_module_names - set(
                    upgradable_modules.mapped("name")
                ):
                    _debug.logic(
                        "cli.module.modules_skipped",
                        verb="upgrade",
                        reason="not_in_db",
                        count=len(unknown_in_db),
                    )
                    _logger.warning(
                        "Ignoring modules not found in the database: %s",
                        ", ".join(sorted(unknown_in_db)),
                    )
                if not_installed := upgradable_modules.filtered(
                    lambda m: m.state not in ("installed", "to upgrade")
                ):
                    _debug.logic(
                        "cli.module.modules_skipped",
                        verb="upgrade",
                        reason="not_installed",
                        count=len(not_installed),
                    )
                    _logger.warning(
                        "Skipping modules that are not installed: %s",
                        ", ".join(not_installed.mapped("name")),
                    )
                    upgradable_modules -= not_installed
            if parsed_args.outdated:
                before_outdated = len(upgradable_modules)
                upgradable_modules = upgradable_modules.filtered(
                    lambda x: (
                        parse_version(x.manifest_version) > parse_version(x.db_version)
                    ),
                )
                _debug.logic(
                    "cli.module.outdated_filter",
                    candidates=before_outdated,
                    outdated=len(upgradable_modules),
                )
            _debug.pipeline(
                "cli.module.upgrade",
                db=parsed_args.db_name,
                requested=len(parsed_args.modules),
                candidates=len(upgradable_modules),
                outdated_only=parsed_args.outdated,
            )
            if not upgradable_modules:
                if parsed_args.outdated:
                    _debug.logic(
                        "cli.module.nothing_done", verb="upgrade", reason="up_to_date"
                    )
                    _logger.info("Nothing to upgrade: every module is up to date.")
                    return
                _exit_nothing_done("upgrade", parsed_args.modules)
            with _debug.perf(
                "cli.module.upgrade_run", cr=env.cr, modules=len(upgradable_modules)
            ):
                upgradable_modules.button_immediate_upgrade()
            _debug.lifecycle(
                "cli.module.upgraded",
                db=parsed_args.db_name,
                modules=len(upgradable_modules),
            )

    def _uninstall_modules(self, parsed_args: argparse.Namespace) -> None:
        with open_environment(parsed_args.db_name, new_registry=True) as env:
            modules = self._get_modules_named(env, parsed_args.modules)
            if unknown := set(parsed_args.modules) - set(modules.mapped("name")):
                _debug.logic(
                    "cli.module.modules_skipped",
                    verb="uninstall",
                    reason="unknown",
                    count=len(unknown),
                )
                _logger.warning(
                    "Ignoring unknown modules: %s", ", ".join(sorted(unknown))
                )
            _debug.pipeline(
                "cli.module.uninstall",
                db=parsed_args.db_name,
                requested=len(parsed_args.modules),
                candidates=len(modules),
            )
            if not modules:
                _exit_nothing_done("uninstall", parsed_args.modules)
            with _debug.perf(
                "cli.module.uninstall_run", cr=env.cr, modules=len(modules)
            ):
                modules.button_immediate_uninstall()
            _debug.lifecycle(
                "cli.module.uninstalled", db=parsed_args.db_name, modules=len(modules)
            )

    def _force_demo_data(self, parsed_args: argparse.Namespace) -> None:
        with open_environment(parsed_args.db_name, new_registry=True) as env:
            _debug.pipeline("cli.module.force_demo", db=parsed_args.db_name)
            with _debug.perf(
                "cli.module.force_demo_run", cr=env.cr, db=parsed_args.db_name
            ):
                force_demo(env)
            _debug.lifecycle("cli.module.demo_forced", db=parsed_args.db_name)
