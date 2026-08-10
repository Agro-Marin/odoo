from __future__ import annotations

import errno
import logging
import os
import threading
from pathlib import Path

import odoo.addons

inotify = None
watchdog = None

if os.name == "posix":
    try:
        import inotify
        from inotify.adapters import InotifyTrees, TerminalEventException
        from inotify.constants import (
            IN_CREATE,
            IN_MODIFY,
            IN_MOVED_TO,
        )

        INOTIFY_LISTEN_EVENTS = IN_MODIFY | IN_CREATE | IN_MOVED_TO
    except ImportError:
        inotify = None

if not inotify:
    try:
        import watchdog
        from watchdog.events import (
            FileCreatedEvent,
            FileModifiedEvent,
            FileMovedEvent,
        )
        from watchdog.observers import Observer
    except ImportError:
        watchdog = None

_logger = logging.getLogger("odoo.service.server")

_OBSERVER_JOIN_TIMEOUT_S = 5.0


ASSET_SUFFIXES = (".js", ".xml", ".scss", ".css")

OVERFLOW_WD = -1
"""Watch descriptor the kernel reports on ``IN_Q_OVERFLOW``; matches no watch."""

OVERFLOW_PATH = "<inotify-overflow>"
"""Stand-in path for the overflow event, which names no file."""

ASSET_BURST_PATH = "<asset-burst>"
"""Stand-in path for a coalesced invalidation, which covers many files."""


INOTIFY_SYSCTL_DIR = Path("/proc/sys/fs/inotify")

INOTIFY_LIMITS = ("max_user_instances", "max_user_watches")
"""The two caps that both report ENOSPC, in the order the syscalls hit them."""


def inotify_limit_diagnosis(exc: BaseException) -> str:
    """Explain an inotify ENOSPC, which never means disk space.

    inotify spends ``ENOSPC`` on two unrelated caps reached by two different
    syscalls, and ``strerror`` renders both as "No space left on device":

    * ``inotify_init()`` exhausts ``fs.inotify.max_user_instances`` — one
      instance per watcher object, so concurrent servers, test runs and editors
      share a per-*user* pool that defaults to 128 and is reached long before
      anything about files is wrong.
    * ``inotify_add_watch()`` exhausts ``fs.inotify.max_user_watches`` — one
      watch per directory, so a large addons path reaches it instead.

    Naming only one of them sends the reader to the wrong sysctl: raising a
    limit that is nowhere near its cap changes nothing, and the message reads
    like a diagnosis rather than the guess it was. So report both **with their
    current values**, letting whoever is looking see which one is at its cap
    instead of being told. Returns ``""`` for any error that is not ENOSPC.
    """
    if getattr(exc, "errno", None) != errno.ENOSPC:
        return ""
    limits = []
    for name in INOTIFY_LIMITS:
        try:
            value = (INOTIFY_SYSCTL_DIR / name).read_text().strip()
        except OSError:
            value = "unreadable"
        limits.append(f"fs.inotify.{name}={value}")
    return (
        "inotify is out of capacity (ENOSPC — not disk space). One of these is "
        f"at its cap: {', '.join(limits)}. Instances are consumed one per "
        "watcher and shared across every process you run as this user, so "
        "concurrent servers, test runs and an editor will reach that one first."
    )


def inotify_watch_paths() -> list[str]:
    from odoo.tools import config

    roots = list(odoo.addons.__path__)
    if "reload" in config["dev_mode"]:
        return roots
    paths = []
    for root in roots:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for addon in sorted(root_path.iterdir()):
            for kind in ("src", "tests"):
                tree = addon / "static" / kind
                if tree.is_dir():
                    paths.append(str(tree))
    return paths


class FSWatcherBase:
    _reload_triggered = False

    def handle_asset_file(self, path: str) -> None:
        from odoo import db as odoo_db
        from odoo.orm.runtime.registry import Registry
        from odoo.tools import config

        databases = set(Registry.registries.snapshot) | set(config["db_name"] or ())
        for db_name in databases:
            try:
                with odoo_db.db_connect(db_name).cursor() as cr:
                    cr.execute("INSERT INTO orm_signaling_assets DEFAULT VALUES")
            except Exception:
                _logger.warning(
                    "assets watch: could not invalidate %s for %s",
                    db_name,
                    path,
                    exc_info=True,
                )

    def handle_file(self, path: str) -> bool | None:
        from odoo.tools import config

        if path.endswith(ASSET_SUFFIXES) and "/static/" in path:
            if "assets" in config["dev_mode"]:
                self.handle_asset_file(path)
            return None
        if self._reload_triggered:
            return None
        if "reload" not in config["dev_mode"]:
            return None
        if path.endswith(".py") and not Path(path).name.startswith(".~"):
            try:
                source = Path(path).read_bytes() + b"\n"
                compile(source, path, "exec")
            except OSError:
                _logger.error(
                    "autoreload: python code change detected, IOError for %s",
                    path,
                )
            except SyntaxError:
                _logger.error(
                    "autoreload: python code change detected, SyntaxError in %s",
                    path,
                )
            else:
                from . import lifecycle

                if not lifecycle.server_phoenix:
                    self._reload_triggered = True
                    _logger.info(
                        "autoreload: python code updated, autoreload activated"
                    )
                    lifecycle.restart()
                    return True
        return None


class FSWatcherWatchdog(FSWatcherBase):
    def __init__(self) -> None:
        self.observer = Observer()
        paths = list(odoo.addons.__path__)
        _logger.info("Watching %d folder(s) for changes", len(paths))
        for path in paths:
            self.observer.schedule(self, path, recursive=True)

    def dispatch(self, event) -> None:
        if isinstance(event, (FileCreatedEvent, FileModifiedEvent, FileMovedEvent)):
            if not event.is_directory:
                path = getattr(event, "dest_path", "") or event.src_path
                self.handle_file(path)

    def start(self) -> None:
        self.observer.start()
        _logger.info("AutoReload watcher running with watchdog")

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join(timeout=_OBSERVER_JOIN_TIMEOUT_S)
        if self.observer.is_alive():
            _logger.warning(
                "autoreload: watchdog observer did not stop within %.0fs; "
                "continuing shutdown without it",
                _OBSERVER_JOIN_TIMEOUT_S,
            )


class FSWatcherInotify(FSWatcherBase):
    _assets_dirty = False
    _burst_active = False

    def handle_asset_file(self, path: str) -> None:
        self._assets_dirty = True
        if not self._burst_active:
            self._burst_active = True
            self._flush_asset_invalidation()

    def _flush_asset_invalidation(self) -> None:
        if not self._assets_dirty:
            return
        self._assets_dirty = False
        super().handle_asset_file(ASSET_BURST_PATH)

    def _end_burst(self) -> None:
        self._flush_asset_invalidation()
        self._burst_active = False

    def __init__(self) -> None:
        self.started = False
        self._assets_dirty = False
        self._burst_active = False
        self.thread: threading.Thread | None = None
        inotify.adapters._LOGGER.setLevel(logging.ERROR)
        paths = inotify_watch_paths()
        _logger.info("Watching %d folder(s) for changes", len(paths))
        self._build_watcher(paths)

    def _build_watcher(self, paths: list[str], block_duration_s: float = 0.5) -> None:
        self.roots = paths
        try:
            self.watcher = InotifyTrees(
                paths, mask=INOTIFY_LISTEN_EVENTS, block_duration_s=block_duration_s
            )
        except Exception as exc:
            # `InotifyTrees` calls inotify_init() and then add_watch() per path,
            # and the library reports both failures as `InotifyError: Call failed
            # (should not be -1): (-1) ERRNO=(28) [No space left on device]`. That
            # string sends every reader to `df`. Re-raise as an OSError carrying
            # the real errno and an explanation of which caps are in play; the
            # caller in lifecycle.py already degrades to running without a
            # watcher, so this changes what it can SAY, not what it does.
            diagnosis = inotify_limit_diagnosis(exc)
            if not diagnosis:
                raise
            raise OSError(errno.ENOSPC, diagnosis) from exc
        self.watcher._i._Inotify__watches_r[OVERFLOW_WD] = OVERFLOW_PATH

    def _resync(self) -> None:
        _logger.warning(
            "autoreload: inotify queue overflowed — events were lost; "
            "re-arming watches and dropping the asset caches"
        )
        for root in self.roots:
            root_path = Path(root)
            if not root_path.is_dir():
                continue
            self._watch_directory(root_path)
            for directory, _, _ in root_path.walk():
                self._watch_directory(directory)
        self.handle_asset_file(OVERFLOW_PATH)

    def _watch_directory(self, directory: Path) -> None:
        path = str(directory)
        tree = self.watcher._i
        try:
            if tree.add_watch(path, self.watcher._mask) is not None:
                return
            try:
                tree.remove_watch(path, superficial=True)
            except Exception:
                _logger.debug("autoreload: stale watch purge for %s", path)
            tree.add_watch(path, self.watcher._mask)
        except Exception as exc:
            _logger.warning(
                "autoreload: cannot watch %s; edits below it will not be seen. %s",
                directory,
                inotify_limit_diagnosis(exc) or "See the traceback for the cause.",
                exc_info=True,
            )

    def run(self) -> None:
        _logger.info("AutoReload watcher running with inotify")
        dir_creation_events = {"IN_MOVED_TO", "IN_CREATE"}
        while self.started:
            try:
                for event in self.watcher.event_gen(timeout_s=0, yield_nones=False):
                    _, type_names, path, filename = event
                    if "IN_ISDIR" not in type_names:
                        if "IN_DELETE" not in type_names:
                            full_path = str(Path(path, filename))
                            if self.handle_file(full_path):
                                return
                    elif dir_creation_events.intersection(type_names):
                        full_path = Path(path, filename)
                        for root, _, files in full_path.walk():
                            self._watch_directory(root)
                            for file in files:
                                if self.handle_file(str(root / file)):
                                    return
            except TerminalEventException as exc:
                if str(exc) != "IN_Q_OVERFLOW":
                    raise
                self._resync()
            self._end_burst()

    def start(self) -> None:
        self.started = True
        self.thread = threading.Thread(
            target=self.run, name="odoo.service.autoreload.watcher"
        )
        self.thread.daemon = True
        self.thread.start()

    def stop(self) -> None:
        self.started = False
        if self.thread is not None:
            self.thread.join()
            self.thread = None
        self.watcher = None
