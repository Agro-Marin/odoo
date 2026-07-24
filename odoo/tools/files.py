"""
File path and open operations for Odoo addons.
"""

import functools
import os
import sys
import tempfile
import typing
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

import odoo.addons
from .config import config

if typing.TYPE_CHECKING:
    from odoo.api import Environment
else:
    # Environment lives in odoo.orm.runtime, which imports from odoo.tools.
    # Runtime-importing it here would cycle.  Fall back to ``Any`` so
    # introspection tools can resolve the annotation; type checkers still
    # see the real class via the branch above.
    Environment = typing.Any


@functools.lru_cache(maxsize=256)
def _resolve_parent(addons_dir: str) -> tuple[Path, Path]:
    """Return the normalized and resolved forms of an addons-root directory.

    Addons roots (and the temporary directories registered by
    `file_open_temporary_directory`) are stable for the lifetime of the
    process, so their resolution can be cached safely.
    """
    parent_path = Path(os.path.normcase(os.path.normpath(addons_dir)))
    return parent_path, parent_path.resolve()


def file_path(
    file_path: str,
    filter_ext: tuple[str, ...] = ("",),
    env: Environment | None = None,
    *,
    check_exists: bool = True,
) -> str:
    """Verify that a file exists under a known `addons_path` directory and return its full path.

    Examples::

    >>> file_path("hr")
    >>> file_path("hr/static/description/icon.png")
    >>> file_path("hr/static/description/icon.png", filter_ext=(".png", ".jpg"))

    :param str file_path: absolute file path, or relative path within any `addons_path` directory
    :param list[str] filter_ext: optional list of supported extensions (lowercase, with leading dot)
    :param env: optional environment, required for a file path within a temporary directory
        created using `file_open_temporary_directory()`
    :param check_exists: check that the file exists (default: True)
    :return: the absolute path to the file
    :raise FileNotFoundError: if the file is not found under the known `addons_path` directories
    :raise ValueError: if the file doesn't have one of the supported extensions (`filter_ext`)
    """
    fp = Path(file_path)
    is_abs = fp.is_absolute()
    normalized = (
        Path(os.path.normcase(str(fp))).resolve()
        if is_abs
        else Path(os.path.normcase(os.path.normpath(file_path)))
    )

    normalized_str = str(normalized)
    if filter_ext and not normalized_str.lower().endswith(filter_ext):
        raise ValueError("Unsupported file: " + file_path)

    # ignore leading 'addons/' if present, it's the final component of root_path, but
    # may sometimes be included in relative paths
    normalized_str = normalized_str.removeprefix("addons" + os.sep)
    normalized = Path(normalized_str)

    # if path is relative and represents a loaded module, accept only the
    # __path__ for that module; otherwise, search in all accepted paths
    parts = normalized.parts
    if not parts:
        raise FileNotFoundError("File not found: " + file_path)
    if not is_abs and (module := sys.modules.get(f"odoo.addons.{parts[0]}")):
        addons_paths = [str(Path(p).parent) for p in module.__path__]
    else:
        root_path = str(Path(config.root_path).resolve())
        temporary_paths = (
            env.transaction._Transaction__file_open_tmp_paths if env else []
        )
        addons_paths = [*odoo.addons.__path__, root_path, *temporary_paths]

    for addons_dir in addons_paths:
        parent_path, resolved_parent = _resolve_parent(addons_dir)
        if is_abs:
            fpath = normalized
        else:
            fpath = parent_path / normalized
        # Resolve both paths to eliminate '..' segments and symlinks before
        # checking containment — unresolved '..' can escape the parent
        # directory.  Return the resolved spelling as well, so callers get a
        # single canonical path per file.
        resolved_fpath = fpath.resolve()
        if resolved_fpath.is_relative_to(resolved_parent) and (
            # we check existence when asked or we have multiple paths to check
            # (there is one possibility for absolute paths)
            (not check_exists and (is_abs or len(addons_paths) == 1)) or fpath.exists()
        ):
            return str(resolved_fpath)

    raise FileNotFoundError("File not found: " + file_path)


def file_open(
    name: str,
    mode: str = "r",
    filter_ext: tuple[str, ...] = (),
    env: Environment | None = None,
) -> IO[Any]:
    """Open a file from within the addons_path directories, as an absolute or relative path.

    Examples::

        >>> file_open('hr/static/description/icon.png')
        >>> file_open('hr/static/description/icon.png', filter_ext=('.png', '.jpg'))
        >>> with file_open('/opt/odoo/addons/hr/static/description/icon.png', 'rb') as f:
        ...     contents = f.read()

    :param name: absolute or relative path to a file located inside an addon
    :param mode: file open mode, as for `open()`
    :param list[str] filter_ext: optional list of supported extensions (lowercase, with leading dot)
    :param env: optional environment, required to open a file within a temporary directory
        created using `file_open_temporary_directory()`
    :return: file object, as returned by `open()`
    :raise FileNotFoundError: if the file is not found under the known `addons_path` directories
    :raise ValueError: if the file doesn't have one of the supported extensions (`filter_ext`)
    """
    path = file_path(name, filter_ext=filter_ext, env=env, check_exists=False)
    encoding = None
    if "b" not in mode:
        # Force encoding for text mode, as system locale could affect default encoding,
        # even with the latest Python 3 versions.
        # Note: This is not covered by a unit test, due to the platform dependency.
        #       For testing purposes you should be able to force a non-UTF8 encoding with:
        #         `sudo locale-gen fr_FR; LC_ALL=fr_FR.iso8859-1 python3 ...'
        # See also PEP-540, although we can't rely on that at the moment.
        encoding = "utf-8"
    if any(m in mode for m in ("w", "x", "a")) and not Path(path).is_file():
        # Don't let create new files
        raise FileNotFoundError(f"Not a file: {path}")
    return open(path, mode, encoding=encoding)


@contextmanager
def file_open_temporary_directory(env: Environment) -> Generator[str]:
    """Create and return a temporary directory added to the directories `file_open` is allowed to read from.

    `file_open` will be allowed to open files within the temporary directory
    only for environments of the same transaction than `env`.
    Meaning, other transactions/requests from other users or even other databases
    won't be allowed to open files from this directory.

    Examples::

        >>> with odoo.tools.file_open_temporary_directory(self.env) as module_dir:
        ...    with zipfile.ZipFile('foo.zip', 'r') as z:
        ...        z.extract('foo/__manifest__.py', module_dir)
        ...    with odoo.tools.file_open('foo/__manifest__.py', env=self.env) as f:
        ...        manifest = f.read()

    :param env: environment for which the temporary directory is created.
    :return: the absolute path to the created temporary directory
    """
    with tempfile.TemporaryDirectory() as module_dir:
        try:
            env.transaction._Transaction__file_open_tmp_paths.append(module_dir)
            yield module_dir
        finally:
            env.transaction._Transaction__file_open_tmp_paths.remove(module_dir)
