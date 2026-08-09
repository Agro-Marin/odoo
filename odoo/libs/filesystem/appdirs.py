#!/usr/bin/env python3


__all__ = [
    "AppDirs",
    "site_config_dir",
    "site_data_dir",
    "user_cache_dir",
    "user_config_dir",
    "user_data_dir",
    "user_log_dir",
]

__version_info__ = (1, 3, 0)
__version__ = ".".join(str(v) for v in __version_info__)


import os
import sys
from pathlib import Path


def user_data_dir(
    appname: str | None = None,
    appauthor: str | None = None,
    version: str | None = None,
    roaming: bool = False,
) -> str:
    if sys.platform == "win32":
        if appauthor is None:
            appauthor = appname
        const = (roaming and "CSIDL_APPDATA") or "CSIDL_LOCAL_APPDATA"
        path = str(Path(_get_win_folder(const)))
        if appname:
            path = str(Path(path, appauthor, appname))
    elif sys.platform == "darwin":
        path = str(Path("~/Library/Application Support/").expanduser())
        if appname:
            path = str(Path(path, appname))
    else:
        path = os.getenv("XDG_DATA_HOME", str(Path("~/.local/share").expanduser()))
        if appname:
            path = str(Path(path, appname))
    if appname and version:
        path = str(Path(path, version))
    return path


def site_data_dir(
    appname: str | None = None,
    appauthor: str | None = None,
    version: str | None = None,
    multipath: bool = False,
) -> str:
    if sys.platform == "win32":
        if appauthor is None:
            appauthor = appname
        path = str(Path(_get_win_folder("CSIDL_COMMON_APPDATA")))
        if appname:
            path = str(Path(path, appauthor, appname))
    elif sys.platform == "darwin":
        path = "/Library/Application Support"
        if appname:
            path = str(Path(path, appname))
    else:
        path = os.getenv(
            "XDG_DATA_DIRS", os.pathsep.join(["/usr/local/share", "/usr/share"])
        )
        pathlist = [
            str(Path(x.rstrip(os.sep)).expanduser()) for x in path.split(os.pathsep)
        ]
        if appname:
            if version:
                appname = str(Path(appname, version))
            pathlist = [str(Path(x) / appname) for x in pathlist]

        if multipath:
            path = os.pathsep.join(pathlist)
        else:
            path = pathlist[0]
        return path

    if appname and version:
        path = str(Path(path, version))
    return path


def user_config_dir(
    appname: str | None = None,
    appauthor: str | None = None,
    version: str | None = None,
    roaming: bool = False,
) -> str:
    if sys.platform in ["win32", "darwin"]:
        path = user_data_dir(appname, appauthor, None, roaming)
    else:
        path = os.getenv("XDG_CONFIG_HOME", str(Path("~/.config").expanduser()))
        if appname:
            path = str(Path(path, appname))
    if appname and version:
        path = str(Path(path, version))
    return path


def site_config_dir(
    appname: str | None = None,
    appauthor: str | None = None,
    version: str | None = None,
    multipath: bool = False,
) -> str:
    if sys.platform in ["win32", "darwin"]:
        path = site_data_dir(appname, appauthor)
        if appname and version:
            path = str(Path(path, version))
    else:
        path = os.getenv("XDG_CONFIG_DIRS", "/etc/xdg")
        pathlist = [
            str(Path(x.rstrip(os.sep)).expanduser()) for x in path.split(os.pathsep)
        ]
        if appname:
            if version:
                appname = str(Path(appname, version))
            pathlist = [str(Path(x) / appname) for x in pathlist]

        if multipath:
            path = os.pathsep.join(pathlist)
        else:
            path = pathlist[0]
    return path


def user_cache_dir(
    appname: str | None = None,
    appauthor: str | None = None,
    version: str | None = None,
    opinion: bool = True,
) -> str:
    if sys.platform == "win32":
        if appauthor is None:
            appauthor = appname
        path = str(Path(_get_win_folder("CSIDL_LOCAL_APPDATA")))
        if appname:
            path = str(Path(path, appauthor, appname))
            if opinion:
                path = str(Path(path, "Cache"))
    elif sys.platform == "darwin":
        path = str(Path("~/Library/Caches").expanduser())
        if appname:
            path = str(Path(path, appname))
    else:
        path = os.getenv("XDG_CACHE_HOME", str(Path("~/.cache").expanduser()))
        if appname:
            path = str(Path(path, appname))
    if appname and version:
        path = str(Path(path, version))
    return path


def user_log_dir(
    appname: str | None = None,
    appauthor: str | None = None,
    version: str | None = None,
    opinion: bool = True,
) -> str:
    if sys.platform == "darwin":
        path = str(Path(Path("~/Library/Logs").expanduser(), appname))
    elif sys.platform == "win32":
        path = user_data_dir(appname, appauthor, version)
        version = None
        if opinion:
            path = str(Path(path, "Logs"))
    else:
        path = user_cache_dir(appname, appauthor, version)
        version = None
        if opinion:
            path = str(Path(path, "log"))
    if appname and version:
        path = str(Path(path, version))
    return path


class AppDirs:
    def __init__(
        self,
        appname: str,
        appauthor: str | None = None,
        version: str | None = None,
        roaming: bool = False,
        multipath: bool = False,
    ) -> None:
        self.appname: str = appname
        self.appauthor: str | None = appauthor
        self.version: str | None = version
        self.roaming: bool = roaming
        self.multipath: bool = multipath

    @property
    def user_data_dir(self) -> str:
        return user_data_dir(
            self.appname,
            self.appauthor,
            version=self.version,
            roaming=self.roaming,
        )

    @property
    def site_data_dir(self) -> str:
        return site_data_dir(
            self.appname,
            self.appauthor,
            version=self.version,
            multipath=self.multipath,
        )

    @property
    def user_config_dir(self) -> str:
        return user_config_dir(
            self.appname,
            self.appauthor,
            version=self.version,
            roaming=self.roaming,
        )

    @property
    def site_config_dir(self) -> str:
        return site_data_dir(
            self.appname,
            self.appauthor,
            version=self.version,
            multipath=self.multipath,
        )

    @property
    def user_cache_dir(self) -> str:
        return user_cache_dir(self.appname, self.appauthor, version=self.version)

    @property
    def user_log_dir(self) -> str:
        return user_log_dir(self.appname, self.appauthor, version=self.version)


def _get_win_folder_from_registry(csidl_name: str) -> str:
    import winreg as _winreg

    shell_folder_name = {
        "CSIDL_APPDATA": "AppData",
        "CSIDL_COMMON_APPDATA": "Common AppData",
        "CSIDL_LOCAL_APPDATA": "Local AppData",
    }[csidl_name]

    key = _winreg.OpenKey(  # type: ignore[attr-defined]
        _winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    )
    folder, _type = _winreg.QueryValueEx(key, shell_folder_name)  # type: ignore[attr-defined]
    return folder


def _get_win_folder_with_pywin32(csidl_name: str) -> str:
    from win32com.shell import shell, shellcon

    folder = shell.SHGetFolderPath(0, getattr(shellcon, csidl_name), 0, 0)
    try:
        folder = str(folder)

        has_high_char = False
        for c in folder:
            if ord(c) > 255:
                has_high_char = True
                break
        if has_high_char:
            try:
                import win32api

                folder = win32api.GetShortPathName(folder)
            except ImportError:
                pass
    except UnicodeError:
        pass
    return folder


def _get_win_folder_with_ctypes(csidl_name: str) -> str:
    import ctypes

    csidl_const = {
        "CSIDL_APPDATA": 26,
        "CSIDL_COMMON_APPDATA": 35,
        "CSIDL_LOCAL_APPDATA": 28,
    }[csidl_name]

    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl_const, None, 0, buf)  # type: ignore[attr-defined]

    has_high_char = False
    for c in buf:
        if ord(c) > 255:
            has_high_char = True
            break
    if has_high_char:
        buf2 = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(buf.value, buf2, 1024):  # type: ignore[attr-defined]
            buf = buf2

    return buf.value


if sys.platform == "win32":
    try:
        import win32com.shell  # noqa: F401  availability probe: the ImportError picks the fallback

        _get_win_folder = _get_win_folder_with_pywin32
    except ImportError:
        try:
            import ctypes  # noqa: F401  availability probe, as above

            _get_win_folder = _get_win_folder_with_ctypes
        except ImportError:
            _get_win_folder = _get_win_folder_from_registry


if __name__ == "__main__":
    appname = "MyApp"
    appauthor = "MyCompany"

    props = (
        "user_data_dir",
        "site_data_dir",
        "user_config_dir",
        "site_config_dir",
        "user_cache_dir",
        "user_log_dir",
    )

    dirs = AppDirs(appname, appauthor, version="1.0")
    for _prop in props:
        pass

    dirs = AppDirs(appname, appauthor)
    for _prop in props:
        pass

    dirs = AppDirs(appname)
    for _prop in props:
        pass
