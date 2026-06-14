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

Example:

    def upgrade(file_manager):
        files = [f for f in file_manager if f.path.suffix == '.py']
        for fileno, file in enumerate(files, start=1):
            file.content = file.content.replace(..., ...)
            file_manager.print_progress(fileno, len(files))

The command line offers a way to select and run those scripts.

Please note that all the scripts are doing a best-effort a migrating the
source code, they only help do the heavy-lifting, they are not silver
bullets.
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

    import odoo.addons
    from . import Command
except ImportError:
    # Assume the script is directly executed (by opposition to be
    # executed via odoo-bin), happily release/parse_version are
    # standalone so we can hack our way there without importing odoo.
    # Guard the sys.path prepend so repeated imports don't accumulate
    # duplicate entries (relevant under test collection / IDE indexing).
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import release

    # Import parse_version directly from file to avoid shadowing stdlib with libs/
    _parse_version_module = _load_module_from_file(
        "parse_version", ROOT / "libs" / "parse_version.py"
    )
    parse_version = _parse_version_module.parse_version

    class Command:
        """Simplified version of the one in command.py, for standalone execution.

        Caches the parser on first access (mirroring ``cli.command.Command``) so
        subclasses can register arguments incrementally in ``__init__``. Without
        the cache, every ``self.parser`` access returned a fresh parser and all
        registrations were silently dropped.
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
            # Explicit utf-8: source files are utf-8 by convention and the
            # default would follow the process locale (PEP 597).
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
        # The progress line is written to stderr, so probe stderr — the
        # previous import-time probe checked stdout AND froze the decision
        # before any stream redirection could happen.
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
        # Scripts are named {version}-{name}.py. Accept either:
        #   1. an exact stem, e.g. `--script 17.5-00-example`
        #   2. a name-only suffix,  e.g. `--script foo`  → matches `19.0-foo.py`
        # Anchor the suffix form on the hyphen so `foo` does not pick up
        # `19.0-foobar.py` or `18.0-bar-foo-baz.py`.
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
        # Safeguard against path traversal (e.g. `--script ../../etc/x`): the
        # exact-stem branch above does `UPGRADE / f"{stem}.py"`, which a `..`
        # in the stem can escape. Path.relative_to is purely lexical and does
        # NOT raise for `..`, so resolve both sides and compare.
        if not script_path.resolve().is_relative_to(UPGRADE.resolve()):
            raise FileNotFoundError(f"--script {script!r} resolves outside {UPGRADE}")
        module = _load_module_from_file(script_path.name, script_path)
        modules = [(script_path.name, module)]
    else:
        modules = get_upgrade_code_scripts(from_version, to_version)

    file_manager = FileManager(addons_path, glob)
    for _name, module in modules:
        file_manager.print_progress(0)  # 0%
        module.upgrade(file_manager)
        file_manager.print_progress(len(file_manager))  # 100%

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
                # the paths must be resolved already
                else functools.partial(str.split, sep=",")
            ),
            default=config["addons_path"] if config else [],
            metavar="PATH,...",
            help="specify additional addons paths (separated by commas)",
        )

    def run(self, cmdargs: list[str]) -> None:
        options = self.parser.parse_args(cmdargs)
        # Catch inverted ranges early — without this, the version filter in
        # get_upgrade_code_scripts silently matches zero scripts and exits 0,
        # which reads as "nothing to do".
        if options.from_version and options.to_version < options.from_version:
            self.parser.error(
                f"--to {options.to_version} is older than --from {options.from_version}"
            )
        if initialize_sys_path:
            config["addons_path"] = options.addons_path
            initialize_sys_path()
            options.addons_path = odoo.addons.__path__
        else:
            # In standalone mode, type=str.split already returned a list;
            # filter out empty entries that result from a trailing comma.
            options.addons_path = [p for p in options.addons_path if p]
        if not options.addons_path:
            self.parser.error("--addons-path is required when used standalone")
        # Explicit kwargs, NOT migrate(**vars(options)): the splat coupled
        # migrate's signature 1:1 to the argparse namespace, so any new CLI
        # flag became an instant "unexpected keyword argument" TypeError.
        is_dirty = migrate(
            options.addons_path,
            options.glob,
            from_version=options.from_version,
            to_version=options.to_version,
            script=options.script,
            dry_run=options.dry_run,
        )
        sys.exit(int(is_dirty))


if __name__ == "__main__":
    UpgradeCode().run(sys.argv[1:])
