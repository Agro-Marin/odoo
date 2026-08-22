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
    parent_path = Path(os.path.normcase(os.path.normpath(addons_dir)))
    return parent_path, parent_path.resolve()


@functools.lru_cache(maxsize=1)
def _root_path(root: str) -> str:
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
    if env is not None and env.transaction.file_open_tmp_paths:
        return _file_path_uncached(file_path, filter_ext, env, check_exists)
    return _file_path_resolved(file_path, filter_ext, check_exists)


@functools.lru_cache(maxsize=8192)
def _file_path_resolved(
    file_path: str, filter_ext: tuple[str, ...], check_exists: bool
) -> str:
    return _file_path_uncached(file_path, filter_ext, None, check_exists)


def _file_path_uncached(
    file_path: str,
    filter_ext: tuple[str, ...],
    env: Environment | None,
    check_exists: bool,
) -> str:
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
        resolved = os.path.realpath(fpath)
        parent = str(resolved_parent)
        if resolved == parent or resolved.startswith(parent + os.sep):
            return str(fpath)

    raise FileNotFoundError("File not found: " + file_path)


def file_open(
    name: str,
    mode: str = "r",
    filter_ext: tuple[str, ...] = (),
    env: Environment | None = None,
) -> IO[Any]:
    path = file_path(name, filter_ext=filter_ext, env=env, check_exists=False)
    encoding = None
    if "b" not in mode:
        encoding = "utf-8"
    if any(m in mode for m in ("w", "x", "a")) and not Path(path).is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    return open(path, mode, encoding=encoding)


@contextmanager
def file_open_temporary_directory(env: Environment) -> Generator[str]:
    with tempfile.TemporaryDirectory() as module_dir:
        try:
            env.transaction.file_open_tmp_paths.append(module_dir)
            yield module_dir
        finally:
            env.transaction.file_open_tmp_paths.remove(module_dir)
