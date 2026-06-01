"""Filesystem watcher for autoreload — extracted from ``server.py``.

Two backends, picked at import time:

* ``inotify`` (POSIX preferred — kernel events, no polling)
* ``watchdog`` (cross-platform fallback — uses fsevents/kqueue/polling)

The classes are constructed by ``server.start()`` when ``--dev=reload`` is
active.  Both call ``server.restart()`` when a Python source file under
the addons path changes; the call is performed via lazy import so this
module has no top-level dependency on ``server.py``.

Splitting these out of ``server.py`` shaves ~115 lines off a 2000-line
file and groups the autoreload concern in one place — operators looking
for "why did the server reload?" don't have to grep through HTTP, prefork,
and signal-handling code.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

# Backend selection — POSIX prefers inotify (kernel-level, zero polling),
# everything else falls back to watchdog (which itself picks fsevents on
# macOS, ReadDirectoryChangesW on Windows, polling otherwise).
#
# Both names are initialized at module scope unconditionally so that
# ``server.py``'s ``from ._watcher import (..., inotify, watchdog)`` always
# resolves regardless of which backend (if any) is installed. Without this,
# a host with ``inotify`` available but ``watchdog`` absent would fail
# server startup with ``ImportError: cannot import name 'watchdog'`` — the
# ``if not inotify:`` branch below is skipped, leaving ``watchdog`` undefined.
inotify = None
watchdog = None

if os.name == "posix":
    try:
        import inotify  # type: ignore[import-not-found]
        from inotify.adapters import InotifyTrees  # type: ignore[import-not-found]
        from inotify.constants import (  # type: ignore[import-not-found]
            IN_CREATE,
            IN_MODIFY,
            IN_MOVED_TO,
        )

        INOTIFY_LISTEN_EVENTS = IN_MODIFY | IN_CREATE | IN_MOVED_TO
    except ImportError:
        inotify = None  # reset in case partial import bound the name

if not inotify:
    try:
        import watchdog  # type: ignore[import-not-found]
        from watchdog.events import (  # type: ignore[import-not-found]
            FileCreatedEvent,
            FileModifiedEvent,
            FileMovedEvent,
        )
        from watchdog.observers import Observer  # type: ignore[import-not-found]
    except ImportError:
        watchdog = None  # reset in case partial import bound the name
# else-branch intentionally absent: ``watchdog`` is pre-initialized to
# ``None`` above (alongside ``inotify``), so it is bound whether or not
# this branch ran. ``server.py``'s top-level import of both names then
# resolves on every host, regardless of which backend was loaded.

# ``odoo.addons`` is imported after the optional inotify/watchdog blocks
# above so the failure mode of "watcher backend missing" surfaces before
# the (slower, larger) addon namespace is touched.
import odoo.addons  # noqa: E402

_logger = logging.getLogger("odoo.service.server")  # operator log-config preserved


def _trigger_restart() -> None:
    """Call ``lifecycle.restart()`` lazily to avoid an import cycle.

    ``server.py`` imports this module to wire up the watcher; this module
    can't import ``server.py`` (or ``lifecycle.py`` which imports
    ``server.py`` lazily) at top level without breaking that.  The
    per-call lookup is fine — ``restart()`` is invoked rarely (one Python
    source edit per dev iteration).
    """
    from .lifecycle import restart, server_phoenix

    if not server_phoenix:
        _logger.info("autoreload: python code updated, autoreload activated")
        restart()


class FSWatcherBase:
    """Common file-change handler for both backends.

    Compiles the changed file as a syntax check before triggering reload —
    a syntax-broken file would crash the new server immediately, leaving
    the operator with no running instance.  Better to log and skip.
    """

    def handle_file(self, path: str) -> bool | None:
        """Check if a changed file is a Python source and trigger autoreload."""
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
                # Lazy import keeps this module free of a lifecycle.py
                # dependency at top-level (lifecycle imports _watcher).
                from .lifecycle import server_phoenix

                if not server_phoenix:
                    _trigger_restart()
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
        self.observer.join()


class FSWatcherInotify(FSWatcherBase):
    """POSIX inotify backend — no polling, kernel-level events."""

    def __init__(self) -> None:
        self.started = False
        # ignore warnings from inotify in case we have duplicate addons paths.
        inotify.adapters._LOGGER.setLevel(logging.ERROR)
        # recreate a list as InotifyTrees' __init__ deletes the list's items
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
                    # despite not having IN_DELETE in the watcher's mask, the
                    # watcher sends these events when a directory is deleted.
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
        self.thread.join()
        del self.watcher  # ensures inotify watches are freed up before reexec
