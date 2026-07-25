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


@functools.lru_cache(maxsize=512)
def _addons_dir_paths(addons_dir: str) -> tuple[Path, Path]:
    """Return ``(normalised, resolved)`` forms of an addons-path directory.

    Addons roots (and the temporary directories registered by
    `file_open_temporary_directory`) are stable for the lifetime of the
    process, so their resolution can be cached safely.
    """
    parent_path = Path(os.path.normcase(os.path.normpath(addons_dir)))
    return parent_path, parent_path.resolve()


@functools.lru_cache(maxsize=1)
def _root_path(root: str) -> str:
    """Return the resolved ``config.root_path`` (stable for a process)."""
    return str(Path(root).resolve())


if typing.TYPE_CHECKING:
    from odoo.api import Environment
else:
    Environment = typing.Any


def file_path(
    file_path: str,
    filter_ext: tuple[str, ...] = ("",),
    env: Environment | None = None,
    *,
    check_exists: bool = True,
) -> str:
    """Verify that a file exists under a known `addons_path` directory and return its full path.

    Examples::

        >>> file_path("hr")  # doctest: +SKIP
        >>> file_path("hr/static/description/icon.png")  # doctest: +SKIP
        >>> file_path("hr/static/description/icon.png", filter_ext=(".png", ".jpg"))  # doctest: +SKIP

    :param str file_path: absolute file path, or relative path within any `addons_path` directory
    :param filter_ext: optional tuple of supported extensions (lowercase, with leading
        dot); must be a tuple — it is passed straight to ``str.endswith()``
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

    normalized_str = normalized_str.removeprefix("addons" + os.sep)
    normalized = Path(normalized_str)

    parts = normalized.parts
    if not parts:
        raise FileNotFoundError("File not found: " + file_path)
    if not is_abs and (module := sys.modules.get(f"odoo.addons.{parts[0]}")):
        addons_paths = [str(Path(p).parent) for p in module.__path__]
    else:
        temporary_paths = env.transaction.file_open_tmp_paths if env else []
        addons_paths = [
            *odoo.addons.__path__,
            _root_path(config.root_path),
            *temporary_paths,
        ]

    skip_exists_check = not check_exists and (is_abs or len(addons_paths) == 1)

    for addons_dir in addons_paths:
        parent_path, resolved_parent = _addons_dir_paths(addons_dir)
        fpath = normalized if is_abs else parent_path / normalized
        if not (skip_exists_check or fpath.exists()):
            continue
        if fpath.resolve().is_relative_to(resolved_parent):
            return str(fpath)

    raise FileNotFoundError("File not found: " + file_path)


def file_open(
    name: str,
    mode: str = "r",
    filter_ext: tuple[str, ...] = (),
    env: Environment | None = None,
) -> IO[Any]:
    """Open a file from within the addons_path directories, as an absolute or relative path.

    Examples::

        >>> file_open('hr/static/description/icon.png')  # doctest: +SKIP
        >>> file_open('hr/static/description/icon.png', filter_ext=('.png', '.jpg'))  # doctest: +SKIP
        >>> with file_open('/opt/odoo/addons/hr/static/description/icon.png', 'rb') as f:  # doctest: +SKIP
        ...     contents = f.read()

    :param name: absolute or relative path to a file located inside an addon
    :param mode: file open mode, as for `open()`
    :param filter_ext: optional tuple of supported extensions (lowercase, with leading
        dot); must be a tuple — it is passed straight to ``str.endswith()``
    :param env: optional environment, required to open a file within a temporary directory
        created using `file_open_temporary_directory()`
    :return: file object, as returned by `open()`
    :raise FileNotFoundError: if the file is not found under the known `addons_path` directories
    :raise ValueError: if the file doesn't have one of the supported extensions (`filter_ext`)
    """
    path = file_path(name, filter_ext=filter_ext, env=env, check_exists=False)
    encoding = None
    if "b" not in mode:
        encoding = "utf-8"
    if any(m in mode for m in ("w", "x", "a")) and not Path(path).is_file():
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

        >>> with odoo.tools.file_open_temporary_directory(self.env) as module_dir:  # doctest: +SKIP
        ...    with zipfile.ZipFile('foo.zip', 'r') as z:
        ...        z.extract('foo/__manifest__.py', module_dir)
        ...    with odoo.tools.file_open('foo/__manifest__.py', env=self.env) as f:
        ...        manifest = f.read()

    :param env: environment for which the temporary directory is created.
    :return: the absolute path to the created temporary directory
    """
    with tempfile.TemporaryDirectory() as module_dir:
        try:
            env.transaction.file_open_tmp_paths.append(module_dir)
            yield module_dir
        finally:
            env.transaction.file_open_tmp_paths.remove(module_dir)
