#!/usr/bin/env python3

__docformat__ = "restructuredtext en"
__all__ = [
    "F_OK",
    "R_OK",
    "W_OK",
    "X_OK",
    "defpath",
    "defpathext",
    "dirname",
    "pathsep",
    "which",
    "which_files",
]

import pathlib
import sys
from os import F_OK, R_OK, W_OK, X_OK, access, defpath, environ, pathsep
from os.path import dirname, split
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

ENOENT = 2

windows = sys.platform.startswith("win")

default_path = environ.get("PATH", defpath).split(pathsep)

if windows:
    default_path.insert(0, ".")
    seen: set[str] = set()
    deduped = []
    for entry in default_path:
        if entry.lower() not in seen:
            seen.add(entry.lower())
            deduped.append(entry)
    default_path = deduped
    del seen, deduped

    defpathext = [""] + environ.get(
        "PATHEXT", ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC"
    ).lower().split(pathsep)
else:
    defpathext = [""]


def which_files(
    file: str,
    mode: int = F_OK | X_OK,
    path: str | list[str] | None = None,
    pathext: str | list[str] | None = None,
) -> Iterator[str]:
    filepath, file = split(file)

    directories: list[str]
    if filepath:
        directories = [filepath]
    elif path is None:
        directories = default_path
    elif isinstance(path, str):
        directories = path.split(pathsep)
    else:
        directories = path

    extensions: list[str]
    if pathext is None:
        extensions = defpathext
    elif isinstance(pathext, str):
        extensions = pathext.split(pathsep)
    else:
        extensions = pathext

    if "" not in extensions:
        extensions = ["", *extensions]

    for directory in directories:
        basepath = pathlib.Path(directory) / file
        for ext in extensions:
            fullpath = str(basepath) + ext
            if pathlib.Path(fullpath).exists() and access(fullpath, mode):
                yield fullpath


def which(
    file: str,
    mode: int = F_OK | X_OK,
    path: str | list[str] | None = None,
    pathext: str | list[str] | None = None,
) -> str:
    found = next(which_files(file, mode, path, pathext), None)
    if found is None:
        raise OSError(
            ENOENT,
            "%s not found" % ((mode & X_OK and "command") or "file"),
            file,
        )
    return found


if __name__ == "__main__":
    import doctest

    doctest.testmod()
