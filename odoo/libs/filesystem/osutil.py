__all__ = [
    "WINDOWS_RESERVED",
    "clean_filename",
    "is_running_as_nt_service",
    "zip_dir",
]

import os
import re
import zipfile
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

WINDOWS_RESERVED = re.compile(
    r"""
    ^
    # forbidden stems: reserved keywords
    # ``(?:`` non-capturing group -- ``(:?`` was a capturing group starting with
    # an optional colon, so it also matched ``":CON"`` (false positive).
    (?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])
    # even with an extension this is recommended against
    (?:\..*)?
    $
""",
    flags=re.IGNORECASE | re.VERBOSE,
)
_CLEAN_FILENAME_RE = re.compile(r"[^\w_.()\[\] -]+")


def clean_filename(name: str, replacement: str = "") -> str:
    if WINDOWS_RESERVED.match(name):
        return "Untitled"
    return _CLEAN_FILENAME_RE.sub(replacement, name).lstrip(".-") or "Untitled"


def zip_dir(
    path: str | Path,
    stream: IO[bytes],
    include_dir: bool = True,
    fnct_sort: Callable | None = None,
) -> None:
    path = str(Path(path))
    dir_root_path = os.path.realpath(path)
    parent = path.rpartition(os.sep)[0] if include_dir else path
    len_prefix = len(parent)
    if len_prefix:
        len_prefix += 1

    with zipfile.ZipFile(
        stream, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as zipf:
        for dirpath, _dirnames, filenames in os.walk(path):
            filenames = sorted(filenames, key=fnct_sort)
            for fname in filenames:
                p = Path(fname)
                ext = p.suffix or p.stem
                if ext not in [".pyc", ".pyo", ".swp", ".DS_Store"]:
                    fpath = str(Path(dirpath, fname))
                    real_fpath = os.path.realpath(fpath)
                    if (
                        Path(real_fpath).is_file()
                        and os.path.commonpath([dir_root_path, real_fpath])
                        == dir_root_path
                    ):
                        zipf.write(real_fpath, fpath[len_prefix:])


if os.name != "nt":

    def is_running_as_nt_service(service_name: str) -> bool:  # noqa: ARG001  POSIX stub; keeps the NT signature
        return False
else:
    from contextlib import contextmanager

    import win32service as ws
    import win32serviceutil as wsu

    def is_running_as_nt_service(service_name: str) -> bool:

        @contextmanager
        def close_srv(srv: Any) -> Iterator[Any]:
            try:
                yield srv
            finally:
                ws.CloseServiceHandle(srv)

        try:
            with close_srv(
                ws.OpenSCManager(None, None, ws.SC_MANAGER_ALL_ACCESS)
            ) as hscm:
                with close_srv(
                    wsu.SmartOpenService(hscm, service_name, ws.SERVICE_ALL_ACCESS)
                ) as hs:
                    info = ws.QueryServiceStatusEx(hs)
                    return info["ProcessId"] == os.getppid()
        except Exception:
            return False
