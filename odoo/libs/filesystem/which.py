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

defpath = environ.get("PATH", defpath).split(pathsep)

if windows:
    defpath.insert(0, ".")
    seen = set()
    defpath = [d for d in defpath if d.lower() not in seen and not seen.add(d.lower())]
    del seen

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

    if filepath:
        path = (filepath,)
    elif path is None:
        path = defpath
    elif isinstance(path, str):
        path = path.split(pathsep)

    if pathext is None:
        pathext = defpathext
    elif isinstance(pathext, str):
        pathext = pathext.split(pathsep)

    if "" not in pathext:
        pathext = ["", *pathext]

    for directory in path:
        basepath = pathlib.Path(directory) / file
        for ext in pathext:
            fullpath = str(basepath) + ext
            if pathlib.Path(fullpath).exists() and access(fullpath, mode):
                yield fullpath


def which(
    file: str,
    mode: int = F_OK | X_OK,
    path: str | list[str] | None = None,
    pathext: str | list[str] | None = None,
) -> str:
    path = next(which_files(file, mode, path, pathext), None)
    if path is None:
        raise OSError(
            ENOENT,
            "%s not found" % ((mode & X_OK and "command") or "file"),
            file,
        )
    return path


if __name__ == "__main__":
    import doctest

    doctest.testmod()
