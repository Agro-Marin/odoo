"""Filesystem and OS helper utilities."""

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
    """Strip or replace characters that are problematic in a filename.

    Sanitize the input string to make it a valid filename in most operating
    systems (including dropping reserved Windows filenames).

    If this results in an empty string, return "Untitled".

    Allows:

    * any alphanumeric character (unicode)
    * underscore (_) as that's innocuous
    * dot (.) except in leading position to avoid creating dotfiles
    * dash (-) except in leading position to avoid annoyance / confusion with
      command options
    * brackets ([ and ]), while they correspond to shell *character class*
      they're a common way to mark / tag files especially on windows
    * parenthesis ("(" and ")"), a more natural though less common version of
      the former
    * space (" ")

    :param str name: file name to clean up
    :param str replacement:
        replacement string to use for sequences of problematic input, by default
        an empty string to remove them entirely, each contiguous sequence of
        problems is replaced by a single replacement
    :rtype: str
    """
    if WINDOWS_RESERVED.match(name):
        return "Untitled"
    return _CLEAN_FILENAME_RE.sub(replacement, name).lstrip(".-") or "Untitled"


def zip_dir(
    path: str | Path,
    stream: IO[bytes],
    include_dir: bool = True,
    fnct_sort: Callable | None = None,
) -> None:  # TODO add ignore list
    """Write the files under ``path`` into ``stream`` as a ZIP archive.

    :param fnct_sort: function passed to the ``key`` parameter of the built-in
        python ``sorted()`` to control the order of files inside the ZIP archive
    """
    path = str(Path(path))
    # Resolve the archive root once so we can keep every written file scoped to
    # it: a symlink under ``path`` pointing outside the tree must not leak files
    # from elsewhere on disk into the archive (upstream odoo/odoo f2e121db77af).
    dir_root_path = os.path.realpath(path)
    len_prefix = len(str(Path(path).parent)) if include_dir else len(path)
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
                    if Path(real_fpath).is_file() and os.path.commonpath(
                        [dir_root_path, real_fpath]
                    ) == dir_root_path:
                        zipf.write(real_fpath, fpath[len_prefix:])


if os.name != "nt":

    def is_running_as_nt_service(service_name: str) -> bool:
        """Return whether this process runs as the named Windows NT service.

        Always ``False`` off Windows. ``service_name`` is accepted for a uniform
        signature and is supplied by the caller (e.g. ``odoo.release``), keeping
        this module dependency-free.
        """
        return False
else:
    from contextlib import contextmanager

    import win32service as ws
    import win32serviceutil as wsu

    def is_running_as_nt_service(service_name: str) -> bool:
        """Return whether this process runs as the named Windows NT service.

        Queries the Service Control Manager for ``service_name`` and compares its
        process id to this process's parent. ``service_name`` is supplied by the
        caller (e.g. ``odoo.release``), keeping this module dependency-free.
        """
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
