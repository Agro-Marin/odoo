"""Filesystem watcher for autoreload.

Two backends, picked at import time:

* ``inotify`` (POSIX preferred — kernel events, no polling)
* ``watchdog`` (cross-platform fallback — uses fsevents/kqueue/polling)

Constructed by ``lifecycle.start()`` when ``--dev=reload`` is active.  Both call
``lifecycle.restart()`` when a Python source file under the addons path changes
(lazy import, so this module has no top-level dependency on ``lifecycle``).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

inotify = None
watchdog = None

if os.name == "posix":
    try:
        import inotify
        from inotify.adapters import InotifyTrees
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

import odoo.addons

_logger = logging.getLogger("odoo.service.server")

_OBSERVER_JOIN_TIMEOUT_S = 5.0


class FSWatcherBase:
    """Common file-change handler for both backends.

    Compiles the changed file as a syntax check before reloading: a
    syntax-broken file would crash the new server, leaving no running instance.
    Log and skip instead.
    """

    _reload_triggered = False

    def handle_file(self, path: str) -> bool | None:
        """Check if a changed file is a Python source and trigger autoreload."""
        if self._reload_triggered:
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
    """Cross-platform fallback using the ``watchdog`` library."""

    def __init__(self) -> None:
        self.observer = Observer()
        for path in odoo.addons.__path__:
            _logger.info("Watching addons folder %s", path)
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
    """POSIX inotify backend — no polling, kernel-level events."""

    def __init__(self) -> None:
        self.started = False
        self.thread: threading.Thread | None = None
        inotify.adapters._LOGGER.setLevel(logging.ERROR)
        paths_to_watch = list(odoo.addons.__path__)
        for path in paths_to_watch:
            _logger.info("Watching addons folder %s", path)
        self.watcher = InotifyTrees(
            paths_to_watch, mask=INOTIFY_LISTEN_EVENTS, block_duration_s=0.5
        )

    def run(self) -> None:
        _logger.info("AutoReload watcher running with inotify")
        dir_creation_events = {"IN_MOVED_TO", "IN_CREATE"}
        while self.started:
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
                        for file in files:
                            if self.handle_file(str(root / file)):
                                return

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
