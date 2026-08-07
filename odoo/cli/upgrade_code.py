#!/usr/bin/env python3

"""
Rewrite the entire source code using the scripts found at
/odoo/upgrade_code

Each script is named {version}-{name}.py and exposes an upgrade function
that takes a single argument, the file_manager, and returns nothing.

The file_manager acts as a list of files, files have 3 attributes:
* path: the pathlib.Path where the file is on the file system;
* addon: the odoo addon in which the file is;
* content: the re-writtable content of the file (lazy).

There are additional utilities on the file_manager, such as:
* print_progress(current, total)

Example::

    def upgrade(file_manager):
        files = [f for f in file_manager if f.path.suffix == ".py"]
        for fileno, file in enumerate(files, start=1):
            file.content = file.content.replace(..., ...)
            file_manager.print_progress(fileno, len(files))

The command line offers a way to select and run those scripts.

All scripts are best-effort: they do the heavy lifting of migrating the
source code, but they are not silver bullets.

**Read this before running any of them.** "Best-effort" undersells the risk:
these scripts rewrite source **in place**, in whatever checkout you point them
at, and until 2026-08 not one of them had a single test. Two of the three that
have since been audited were found to corrupt the tree they were run on:

* ``18.1-00-sql-constraint.py`` caught only ``SyntaxError`` from
  ``ast.literal_eval``, which raises **ValueError** for a non-literal node — and
  the commonest real ``_sql_constraints`` entry carries a translated message,
  ``_('...')``, which is a Call. The escaping ValueError aborted the whole run
  partway through the file list, leaving everything already processed rewritten.
  It also emitted ``_{name} = models.Constraint(...)`` unconditionally, so a
  constraint named ``name`` silently redefined the model's ``_name`` and
  destroyed its identity (19 ``BaseModel`` attributes were reachable that way).
* ``18.5-00-deprecated-properties.py`` was a bare regex, so it rewrote inside
  string literals and comments, turned ``self.env._cr`` into
  ``self.env.env.cr``, and turned ``self._cr = cr`` in a non-recordset
  ``__init__`` into ``self.env.cr = cr``. Run against this repository it would
  have broken ``db/savepoint.py``, ``tools/translate.py`` and
  ``web/controllers/json_helpers.py``.

Both are fixed and now have tests (``odoo/tools/tests/
test_upgrade_code_sql_constraint.py`` and
``…_deprecated_properties.py``). The remaining seven scripts are **still
untested**, and the two audited ones were not unusual — they are text
substitutions standing in for code transformations.

So, in order:

1. ``--dry-run`` first, and read the file list.
2. ``--glob`` to scope the run; do not rewrite a whole checkout in one pass.
3. Diff and read every change before committing. One limitation is inherent:
   whether ``x`` in ``x._context`` is a recordset cannot be decided statically,
   so a rewrite on a non-recordset is possible by construction, not by defect.
4. Work on a clean tree so ``git diff`` is the review, and ``git checkout`` the
   undo.
"""

import argparse
import functools
import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parent.parent
UPGRADE = ROOT / "upgrade_code"
AVAILABLE_EXT = (".py", ".js", ".css", ".scss", ".xml", ".csv", ".po", ".pot")


def _load_module_from_file(name: str, path: str | Path) -> ModuleType:
    """Load a Python module from a file path using importlib.

    Replaces the deprecated ``SourceFileLoader.load_module()`` (removed in 3.15).
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from odoo import release
    from odoo.libs.parse_version import parse_version
    from odoo.modules import initialize_sys_path
    from odoo.tools import config

    from . import Command
except ImportError:
    release = _load_module_from_file("release", ROOT / "release.py")
    _parse_version_module = _load_module_from_file(
        "parse_version", ROOT / "libs" / "parse_version.py"
    )
    parse_version = _parse_version_module.parse_version

    class Command:
        """Simplified ``cli.command.Command`` for standalone execution.

        Caches the parser so a subclass can register args incrementally in
        ``__init__``; without it each ``self.parser`` access dropped them.
        """

        def __init__(self) -> None:
            self._parser: argparse.ArgumentParser | None = None

        @property
        def parser(self) -> argparse.ArgumentParser:
            if self._parser is None:
                self._parser = argparse.ArgumentParser(
                    prog=Path(sys.argv[0]).name,
                    description=__doc__.replace("/odoo/upgrade_code", str(UPGRADE)),
                    formatter_class=argparse.RawDescriptionHelpFormatter,
                )
            return self._parser

    config = None
    initialize_sys_path = None


class FileAccessor:
    addon: Path
    path: Path
    content: str

    def __init__(self, path: Path, addon_path: Path) -> None:
        self.path = path
        self.addon = addon_path / path.relative_to(addon_path).parts[0]
        self._content: str | None = None
        self.dirty: bool = False

    @property
    def content(self) -> str:
        if self._content is None:
            self._content = self.path.read_text(encoding="utf-8")
        return self._content

    @content.setter
    def content(self, value: str) -> None:
        if self._content != value:
            self._content = value
            self.dirty = True


class FileManager:
    addons_path: list[str]
    glob: str

    def __init__(self, addons_path: list[str], glob: str = "**/*") -> None:
        self.addons_path = addons_path
        self.glob = glob
        self._files = {
            str(path): FileAccessor(path, Path(addon_path))
            for addon_path in addons_path
            for path in Path(addon_path).glob(glob)
            if "__pycache__" not in path.parts
            if path.suffix in AVAILABLE_EXT
            if path.is_file()
        }
        self._show_progress = sys.stderr.isatty()

    def __iter__(self) -> Iterator[FileAccessor]:
        return iter(self._files.values())

    def __len__(self) -> int:
        return len(self._files)

    def get_file(self, path: str | Path) -> FileAccessor | None:
        return self._files.get(str(path))

    def print_progress(
        self,
        current: int,
        total: int | None = None,
        file_name: str | Path = "",
    ) -> None:
        """Render a one-line progress indicator on interactive stderr."""
        if not self._show_progress:
            return
        total = total or len(self) or 1
        print(
            f"\033[K{current / total:>4.0%} \033[37m{file_name}\033[0m",
            end="\r",
            file=sys.stderr,
        )

    def clear_progress(self) -> None:
        """Erase the progress line, so the last `\\r`-terminated render isn't
        left under the subsequent stdout output (or the shell prompt)."""
        if self._show_progress:
            print("\033[K", end="", file=sys.stderr, flush=True)


def get_upgrade_code_scripts(
    from_version: tuple[int, ...], to_version: tuple[int, ...]
) -> list[tuple[str, ModuleType]]:
    modules: list[tuple[str, ModuleType]] = []
    for script_path in sorted(UPGRADE.glob("*.py")):
        version = parse_version(script_path.name.partition("-")[0])
        if from_version <= version <= to_version:
            module = _load_module_from_file(script_path.name, script_path)
            modules.append((script_path.name, module))
    return modules


def migrate(
    addons_path: list[str],
    glob: str,
    from_version: tuple[int, ...] | None = None,
    to_version: tuple[int, ...] | None = None,
    script: str | None = None,
    dry_run: bool = False,
) -> bool:
    if script:
        stem = script.removesuffix(".py")
        exact = UPGRADE / f"{stem}.py"
        if exact.is_file():
            candidates = [exact]
        else:
            candidates = sorted(UPGRADE.glob(f"*-{stem}.py"))
        if len(candidates) > 1:
            raise FileNotFoundError(
                f"--script {script!r} is ambiguous: matches "
                f"{[p.name for p in candidates]}"
            )
        script_path = candidates[0] if candidates else None
        if not script_path:
            raise FileNotFoundError(script)
        if not script_path.resolve().is_relative_to(UPGRADE.resolve()):
            raise FileNotFoundError(f"--script {script!r} resolves outside {UPGRADE}")
        module = _load_module_from_file(script_path.name, script_path)
        modules = [(script_path.name, module)]
    else:
        modules = get_upgrade_code_scripts(from_version, to_version)

    file_manager = FileManager(addons_path, glob)
    for _name, module in modules:
        file_manager.print_progress(0)
        module.upgrade(file_manager)
        file_manager.print_progress(len(file_manager))
    file_manager.clear_progress()

    for file in file_manager:
        if file.dirty:
            print(file.path)
            if not dry_run:
                with file.path.open("w", encoding="utf-8") as f:
                    f.write(file.content)

    return any(file.dirty for file in file_manager)


class UpgradeCode(Command):
    """Rewrite the entire source code using the scripts found at /odoo/upgrade_code"""

    name = "upgrade_code"

    def __init__(self) -> None:
        super().__init__()
        group = self.parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--script", metavar="NAME", help="run this single script")
        group.add_argument(
            "--from",
            dest="from_version",
            type=parse_version,
            metavar="VERSION",
            help="run all scripts starting from this version, inclusive",
        )
        self.parser.add_argument(
            "--to",
            dest="to_version",
            type=parse_version,
            default=parse_version(release.version),
            metavar="VERSION",
            help=f"run all scripts until this version, inclusive (default: {release.version})",
        )
        self.parser.add_argument(
            "--glob",
            default="**/*",
            help="select the files to rewrite (default: %(default)s)",
        )
        self.parser.add_argument(
            "--dry-run",
            action="store_true",
            help="list the files that would be re-written, but rewrite none",
        )
        self.parser.add_argument(
            "--addons-path",
            type=(
                functools.partial(config.parse, "addons_path")
                if config
                else functools.partial(str.split, sep=",")
            ),
            default=config["addons_path"] if config else [],
            metavar="PATH,...",
            help="specify additional addons paths (separated by commas)",
        )

    def run(self, cmdargs: list[str]) -> None:
        options = self.parser.parse_args(cmdargs)
        if options.from_version and options.to_version < options.from_version:
            self.parser.error(
                f"--to {options.to_version} is older than --from {options.from_version}"
            )
        requested = [p for p in options.addons_path if p]
        if not requested and initialize_sys_path:
            requested = [p for p in config["addons_path"] if p]
        if initialize_sys_path:
            config["addons_path"] = requested
            initialize_sys_path()
        options.addons_path = requested
        if not options.addons_path:
            self.parser.error("--addons-path is required")
        is_dirty = migrate(
            options.addons_path,
            options.glob,
            from_version=options.from_version,
            to_version=options.to_version,
            script=options.script,
            dry_run=options.dry_run,
        )
        sys.exit(int(is_dirty) if options.dry_run else 0)


if __name__ == "__main__":
    UpgradeCode().run(sys.argv[1:])
