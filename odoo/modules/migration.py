import inspect
import itertools
import logging
import re
import typing
from collections import defaultdict
from pathlib import Path

import odoo.upgrade
from odoo import release
from odoo.libs.parse_version import parse_version
from odoo.modules.module import load_script
from odoo.tools.misc import file_path

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

    from odoo.db import Cursor

    from . import module_graph

_logger = logging.getLogger(__name__)


# Reviewed 2026-03: pre-7.0 patterns (6.1, saas~) are intentionally kept — multi-version
# upgrade scripts and odoo.upgrade paths may contain historical version folders.
# The regex is compiled once; zero runtime cost.
VERSION_RE = re.compile(
    r"""^
        # Optional prefix with Odoo version
        ((
            6\.1|

            # "x.0" version, with x >= 6.
            [6-9]\.0|

            # multi digits "x.0" versions
            [1-9]\d+\.0|

            # x.saas~y, where x >= 7 and x <= 10
            (7|8|9|10)\.saas~[1-9]\d*|

            # saas~x.y, where x >= 11 (any number of digits) and y between 1 and 9
            saas~(1[1-9]|[2-9]\d|[1-9]\d{2,})\.[1-9]
        )\.)?
        # After Odoo version we allow precisely 2 or 3 parts
        # note this will also allow 0.0.0 which has a special meaning
        \d+\.\d+(\.\d+)?
    $""",
    re.VERBOSE | re.ASCII,
)


def _convert_version(version: str) -> str:
    """Normalize a migration-folder name to a comparable version string.

    A bare ``x.y[.z]`` module version is prefixed with the server major version;
    a name that already carries the server version (more than two dots) and the
    special ``0.0.0`` marker are returned unchanged.
    """
    if version == "0.0.0":
        return version
    if version.count(".") > 2:
        # the version number already contains the server version, see VERSION_RE
        return version
    return f"{release.major_version}.{version}"


def _migration_applies(
    version: str, installed_version: str, target_version: str
) -> bool:
    """Return whether the migration folder ``version`` must run for this upgrade.

    :param version: migration folder name ('2.0', '0.0.0', '17.0.1.2', ...)
    :param installed_version: module version currently recorded in the database
    :param target_version: module version declared in the manifest being upgraded to
    """
    parsed_installed = parse_version(installed_version or "")
    parsed_target = parse_version(_convert_version(target_version))

    if version == "0.0.0" and parsed_installed < parsed_target:
        return True

    full_version = _convert_version(version)
    if version != full_version:
        # A "majorless" script (e.g. '2.0') must not re-run when only the Odoo
        # major version bumps: compare just the module part so a 9.0.2.0 ->
        # 10.0.2.0 upgrade does not replay the 2.0 script.
        return (
            parsed_installed[2:] < parse_version(full_version)[2:] <= parsed_target[2:]
        )

    return parsed_installed < parse_version(full_version) <= parsed_target


def _iter_upgrade_paths(pkg: str) -> Iterator[str]:
    """Yield the existing ``odoo.upgrade/<pkg>`` directories on the upgrade path."""
    for path in odoo.upgrade.__path__:  # type: ignore[attr-defined]
        upgrade_path = Path(path, pkg)
        if upgrade_path.exists():
            yield str(upgrade_path)


def _is_upgrade_version_dir(path: str, version: str) -> bool:
    """Return whether ``<path>/<version>`` is a valid migration version folder."""
    full_path = Path(path, version)
    if not full_path.is_dir():
        return False
    if version == "tests":
        return False
    if not VERSION_RE.match(version):
        _logger.warning("Invalid version for upgrade script %r", str(full_path))
        return False
    return True


def _scripts_by_version(path: str) -> dict[str, list[str]]:
    """Map each valid version folder under ``path`` to its list of ``.py`` scripts."""
    if not path:
        return {}
    p = Path(path)
    return {
        entry.name: [str(f) for f in (p / entry.name).glob("*.py")]
        for entry in p.iterdir()
        if _is_upgrade_version_dir(path, entry.name)
    }


def _resolve_addon_path(path: str) -> str:
    """Resolve an addon-relative path to an absolute one, or '' if it does not exist."""
    try:
        return file_path(path)
    except FileNotFoundError:
        return ""


class MigrationManager:
    """Manages the migration of modules.

    Migrations files must be python files containing a ``migrate(cr, version)``
    function. These files must respect a directory tree structure: A 'migrations' folder
    which contains a folder by version. Version can be 'module' version or 'server.module'
    version (in this case, the files will only be processed by this version of the server).
    Python file names must start by ``pre-`` or ``post-`` and will be executed, respectively,
    before and after the module initialisation. ``end-`` scripts are run after all modules have
    been updated.

    A special folder named ``0.0.0`` can contain scripts that will be run on any version change.
    In `pre` stage, ``0.0.0`` scripts are run first, while in ``post`` and ``end``, they are run last.

    Example::

        <moduledir>
        `-- migrations
            |-- 1.0
            |   |-- pre-update_table_x.py
            |   |-- pre-update_table_y.py
            |   |-- post-create_plop_records.py
            |   |-- end-cleanup.py
            |   `-- README.txt                      # not processed
            |-- 9.0.1.1                             # processed only on a 9.0 server
            |   |-- pre-delete_table_z.py
            |   `-- post-clean-data.py
            |-- 0.0.0
            |   `-- end-invariants.py               # processed on all version update
            `-- foo.py                              # not processed
    """

    migrations: defaultdict[str, dict]

    def __init__(self, cr: Cursor, graph: module_graph.ModuleGraph) -> None:
        self.cr = cr
        self.graph = graph
        self.migrations = defaultdict(dict)
        self._get_files()

    def _needs_migration(self, pkg: module_graph.ModuleNode) -> bool:
        """Whether ``pkg`` should have its migration scripts collected/run."""
        return pkg.load_state == "to upgrade"

    def _get_files(self) -> None:
        for pkg in self.graph:
            if not self._needs_migration(pkg):
                continue

            self.migrations[pkg.name] = {
                "module": _scripts_by_version(
                    _resolve_addon_path(pkg.name + "/migrations")
                ),
                "module_upgrades": _scripts_by_version(
                    _resolve_addon_path(pkg.name + "/upgrades")
                ),
            }

            scripts = defaultdict(list)
            for p in _iter_upgrade_paths(pkg.name):
                for v, s in _scripts_by_version(p).items():
                    scripts[v].extend(s)
            self.migrations[pkg.name]["upgrade"] = scripts

    def migrate_module(
        self,
        pkg: module_graph.ModuleNode,
        stage: typing.Literal["pre", "post", "end"],
    ) -> None:
        assert stage in ("pre", "post", "end")
        stageformat = {
            "pre": "[>%s]",
            "post": "[%s>]",
            "end": "[$%s]",
        }
        if not self._needs_migration(pkg):
            return

        def _get_migration_versions(
            pkg: module_graph.ModuleNode, stage: str
        ) -> list[str]:
            versions = sorted(
                {
                    ver
                    for lv in self.migrations[pkg.name].values()
                    for ver, lf in lv.items()
                    if lf
                },
                key=lambda k: parse_version(_convert_version(k)),
            )
            if "0.0.0" in versions:
                # reorder versions
                versions.remove("0.0.0")
                if stage == "pre":
                    versions.insert(0, "0.0.0")
                else:
                    versions.append("0.0.0")
            return versions

        def _get_migration_files(
            pkg: module_graph.ModuleNode, version: str, stage: str
        ) -> list[str]:
            """return a list of migration script files"""
            m = self.migrations[pkg.name]

            # Sort by (filename, full_path) so files with the same basename in
            # different source dirs (module/migrations, module/upgrades, and
            # odoo.upgrade/<pkg>) get a deterministic order rather than dict-
            # iteration order.
            return sorted(
                (
                    f
                    for k in m
                    for f in m[k].get(version, [])
                    if Path(f).name.startswith(f"{stage}-")
                ),
                key=lambda f: (Path(f).name, f),
            )

        installed_version = pkg.load_version or ""
        target_version = pkg.manifest["version"]

        versions = _get_migration_versions(pkg, stage)
        for version in versions:
            if _migration_applies(version, installed_version, target_version):
                for pyfile in _get_migration_files(pkg, version, stage):
                    exec_script(
                        self.cr,
                        installed_version,
                        pyfile,
                        pkg.name,
                        stage,
                        stageformat[stage] % version,
                    )


# Reviewed 2026-03: _cr/_version variants are kept for backward compatibility
# with existing migration scripts.  Zero cost, removing would break silently.
VALID_MIGRATE_PARAMS = list(
    itertools.product(
        ["cr", "_cr"],
        ["version", "_version"],
    )
)


def exec_script(
    cr: Cursor,
    installed_version: str,
    pyfile: str,
    addon: str,
    stage: str,
    version: str | None = None,
) -> None:
    """Execute a single migration script file."""
    version = version or installed_version
    p = Path(pyfile)
    if p.suffix.lower() != ".py":
        return
    try:
        mod = load_script(pyfile, p.stem)
    except ImportError as e:
        raise ImportError(
            f"module {addon}: Unable to load {stage}-migration file {pyfile}"
        ) from e

    if not hasattr(mod, "migrate"):
        raise AttributeError(
            f"module {addon}: Each {stage}-migration file must have a"
            f' "migrate(cr, installed_version)" function, not found in {pyfile}'
        )

    try:
        sig = inspect.signature(mod.migrate)
    except TypeError as e:
        raise TypeError(
            f"module {addon}: `migrate` needs to be a function, got {mod.migrate!r}"
        ) from e

    if not (
        tuple(sig.parameters.keys()) in VALID_MIGRATE_PARAMS
        and all(
            param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
            for param in sig.parameters.values()
        )
    ):
        raise TypeError(
            f"module {addon}: `migrate`'s signature should be `(cr, version)`,"
            f" {mod.migrate} is {sig}"
        )

    _logger.info("module %s: Running migration %s %s", addon, version, mod.__name__)
    mod.migrate(cr, installed_version)
