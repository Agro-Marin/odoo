import annotationlib
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


MIGRATION_STAGES: tuple[str, ...] = ("pre", "post", "end")
"""The stages ``migrate_module`` runs, and the filename prefixes that select them.

``_get_migration_files`` picks scripts with ``name.startswith(f"{stage}-")``, so
the stage is carried entirely by the filename and a name matching none of these
is collected and then never executed.
"""

_STAGE_PREFIXES: tuple[str, ...] = tuple(f"{stage}-" for stage in MIGRATION_STAGES)


def _warn_unstaged_scripts(directory: Path, files: list[str]) -> None:
    """Warn about scripts that will never run because no stage claims them.

    ``risks.md`` R3 records that migration staging is unenforced. That is true of
    the *semantic* half — nothing can know that a script reading the old schema
    was filed as ``post-`` — but not of the syntactic half, which is checkable
    and was not checked: a file named ``pre_01.py`` or ``Pre-01.py`` (the match is
    case-sensitive) is globbed by ``_scripts_by_version`` and then silently
    dropped by every stage. On an upgrade of a populated database that is a
    migration nobody notices did not happen.

    A warning rather than an error, for the same reason ``_is_upgrade_version_dir``
    warns on a malformed version directory: an addon may legitimately keep a
    helper module beside its scripts, and refusing to upgrade over one would be a
    worse failure than the one being reported.

    Measured over **this repository's two addon trees** (``odoo/addons`` and
    ``addons``) on 2026-08-15: 145 migration scripts, all correctly prefixed,
    0 skipped. The *property* is what is pinned —
    ``test_migration_stages.test_none_of_them_is_skipped`` re-derives it from the
    tree on every run and names any script no stage would claim. The count beside
    it is a dated measurement, not a pin: it moves whenever any author in either
    tree adds a script, and a live pin on it made this file a serialization point
    for all of them.

    The scope is this repo on purpose. The figure here read "223 across this
    workspace's five addon trees", which CI could never reproduce because it
    checks out this repo alone, so the number could be neither confirmed nor
    refuted from inside the build that was supposed to be keeping it honest —
    and it had already drifted to 235 by the time anyone counted.

    The test globs the working tree, not the index, which is deliberate: whoever
    adds a script sees the gate go red on the spot rather than in someone else's
    CI run. In this workspace that also means an *uncommitted* script in another
    session's tree moves the number locally, so re-measure against a clean
    checkout of HEAD before believing a count that disagrees with this one.
    """
    for path in files:
        name = Path(path).name
        if name.startswith(_STAGE_PREFIXES) or name == "__init__.py":
            continue
        _logger.warning(
            "Migration script %s will never run: its name matches no stage. "
            "Rename it to one of %s (lower-case, hyphen) or move it out of %s.",
            path,
            ", ".join(f"{p}*.py" for p in _STAGE_PREFIXES),
            directory,
        )


def _convert_version(version: str) -> str:
    if version == "0.0.0":
        return version
    if version.count(".") > 2:
        return version
    return f"{release.major_version}.{version}"


def _migration_applies(
    version: str, installed_version: str, target_version: str
) -> bool:
    parsed_installed = parse_version(installed_version or "")
    parsed_target = parse_version(_convert_version(target_version))

    if version == "0.0.0" and parsed_installed < parsed_target:
        return True

    full_version = _convert_version(version)
    if version != full_version:
        return (
            parsed_installed[2:] < parse_version(full_version)[2:] <= parsed_target[2:]
        )

    return parsed_installed < parse_version(full_version) <= parsed_target


def _iter_upgrade_paths(pkg: str) -> Iterator[str]:
    for path in odoo.upgrade.__path__:
        upgrade_path = Path(path, pkg)
        if upgrade_path.exists():
            yield str(upgrade_path)


def _is_upgrade_version_dir(path: str, version: str) -> bool:
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
    if not path:
        return {}
    p = Path(path)
    by_version = {
        entry.name: [str(f) for f in (p / entry.name).glob("*.py")]
        for entry in p.iterdir()
        if _is_upgrade_version_dir(path, entry.name)
    }
    for version, files in by_version.items():
        _warn_unstaged_scripts(p / version, files)
    return by_version


def _resolve_addon_path(path: str) -> str:
    try:
        return file_path(path)
    except FileNotFoundError:
        return ""


class MigrationManager:
    migrations: dict[str, dict]

    def __init__(self, cr: Cursor, graph: module_graph.ModuleGraph) -> None:
        self.cr = cr
        self.graph = graph
        self.migrations = {}
        self._get_files()

    def _needs_migration(self, pkg: module_graph.ModuleNode) -> bool:
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
        assert stage in MIGRATION_STAGES
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
                versions.remove("0.0.0")
                if stage == "pre":
                    versions.insert(0, "0.0.0")
                else:
                    versions.append("0.0.0")
            return versions

        def _get_migration_files(
            pkg: module_graph.ModuleNode, version: str, stage: str
        ) -> list[str]:
            m = self.migrations[pkg.name]

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
        sig = inspect.signature(
            mod.migrate, annotation_format=annotationlib.Format.FORWARDREF
        )
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
