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

OVERFLOW_PATH = "<inotify-overflow>"

ASSET_BURST_PATH = "<asset-burst>"


INOTIFY_SYSCTL_DIR = Path("/proc/sys/fs/inotify")

INOTIFY_LIMITS = ("max_user_instances", "max_user_watches")


def inotify_limit_diagnosis(exc: BaseException) -> str:
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


class FSWatcherBase:
    #: Trailing-flush delay for backends that have no end-of-pass boundary of
    #: their own. Short enough to stay inside an edit/reload loop, long enough
    #: that a multi-file save collapses into one signal.
    _BURST_FLUSH_S = 0.2

    #: False for backends that emit the trailing edge themselves.
    _needs_burst_timer = True

    _reload_triggered = False

    def __init__(self) -> None:
        self._burst_lock = threading.Lock()
        self._assets_dirty = False
        self._burst_active = False
        self._burst_timer: threading.Timer | None = None

    @staticmethod
    def watch_paths() -> list[str]:
        """Directories to watch, for BOTH backends.

        This belongs to the base class because the answer must not depend on
        which optional library happens to be installed.  It used to: the inotify
        backend narrowed the tree in assets-only mode while the watchdog backend
        always scheduled the addons roots recursively, so the same
        ``--dev=assets`` run watched a different set of files on two machines
        that differed only in whether ``inotify`` was importable.

        With ``reload`` in ``dev_mode`` the whole addons tree is in scope --
        Python sources can be anywhere in it.  Otherwise only assets can trigger
        anything, and ``handle_file`` acts on a path exactly when it has an asset
        suffix and ``/static/`` in it, so each addon's ``static/`` tree is both
        the necessary and the sufficient scope.

        Watching ``static/`` whole, rather than enumerating ``static/src`` and
        ``static/tests``, also closes a gap the narrower list had: everything
        under ``static/lib`` is bundled and was watched by watchdog but not by
        inotify, so editing a vendored library invalidated the bundles on one
        backend and did nothing on the other.
        """
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
                tree = addon / "static"
                if tree.is_dir():
                    paths.append(str(tree))
        return paths

    def _signal_asset_change(self, path: str) -> None:
        """One transaction per database. The expensive half of an invalidation."""
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

    def handle_asset_file(self, path: str) -> None:
        """Signal on the leading edge, then coalesce the rest of the burst.

        Without this, a compile that touches N files with D databases open costs
        N x D transactions -- measured at 60 cursors for 20 files across three
        databases, against 6 with coalescing. This lived only in the inotify
        backend, so which of those two a developer paid depended on which
        optional library was installed.

        The leading edge keeps a single edit as prompt as an uncoalesced signal;
        everything after it collapses into one trailing flush.
        """
        with self._burst_lock:
            self._assets_dirty = True
            leading = not self._burst_active
            if leading:
                self._burst_active = True
        if leading:
            self._flush_asset_invalidation()
        self._arm_burst_flush()

    def _flush_asset_invalidation(self) -> None:
        with self._burst_lock:
            if not self._assets_dirty:
                return
            self._assets_dirty = False
        self._signal_asset_change(ASSET_BURST_PATH)

    def _end_burst(self) -> None:
        """Trailing edge: emit anything pending and re-arm the leading edge."""
        self._cancel_burst_flush()
        self._flush_asset_invalidation()
        with self._burst_lock:
            self._burst_active = False

    def _arm_burst_flush(self) -> None:
        """Schedule the trailing flush for backends with no end-of-pass hook.

        ``FSWatcherInotify`` calls ``_end_burst`` itself once per pass of its
        event generator, so it needs no timer. ``FSWatcherWatchdog`` is called
        back per event by the observer and has no such boundary.
        """
        if not self._needs_burst_timer:
            return
        with self._burst_lock:
            if self._burst_timer is not None:
                self._burst_timer.cancel()
            timer = threading.Timer(self._BURST_FLUSH_S, self._end_burst)
            timer.daemon = True
            self._burst_timer = timer
        timer.start()

    def _cancel_burst_flush(self) -> None:
        with self._burst_lock:
            timer, self._burst_timer = self._burst_timer, None
        if timer is not None:
            timer.cancel()

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
        super().__init__()
        self.observer = Observer()
        paths = self.watch_paths()
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
        self._end_burst()
        self.observer.stop()
        self.observer.join(timeout=_OBSERVER_JOIN_TIMEOUT_S)
        if self.observer.is_alive():
            _logger.warning(
                "autoreload: watchdog observer did not stop within %.0fs; "
                "continuing shutdown without it",
                _OBSERVER_JOIN_TIMEOUT_S,
            )


class FSWatcherInotify(FSWatcherBase):
    # Emits the trailing edge itself: ``run`` calls ``_end_burst`` once per pass
    # of the event generator, which is a real quiescence boundary.
    _needs_burst_timer = False

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.thread: threading.Thread | None = None
        inotify.adapters._LOGGER.setLevel(logging.ERROR)
        paths = self.watch_paths()
        _logger.info("Watching %d folder(s) for changes", len(paths))
        self._build_watcher(paths)

    def _build_watcher(self, paths: list[str], block_duration_s: float = 0.5) -> None:
        self.roots = paths
        try:
            self.watcher = InotifyTrees(
                paths, mask=INOTIFY_LISTEN_EVENTS, block_duration_s=block_duration_s
            )
        except Exception as exc:
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
        self._end_burst()
        if self.thread is not None:
            self.thread.join()
            self.thread = None
        self.watcher = None
