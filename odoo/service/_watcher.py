"""Filesystem watcher for autoreload.

Two backends, picked at import time:

* ``inotify`` (POSIX preferred — kernel events, no polling)
* ``watchdog`` (cross-platform fallback — uses fsevents/kqueue/polling)

Constructed by ``lifecycle.start()`` when ``--dev=reload`` or ``--dev=assets``
is active.  Under ``reload`` both backends call ``lifecycle.restart()`` when a
Python source file under the addons path changes (lazy import, so this module
has no top-level dependency on ``lifecycle``); under ``assets`` a changed
``static/`` asset source drops the assets cache instead of restarting.
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


ASSET_SUFFIXES = (".js", ".xml", ".scss", ".css")


def inotify_watch_paths() -> list[str]:
    """Directories for the ``InotifyTrees`` backend, narrowed to the mode.

    ``reload`` must see every ``.py`` under the addons path, so it watches the
    trees whole. ``assets`` alone only cares about bundled sources, and
    narrowing to ``static/{src,tests}`` cuts the cost from ~20.8k inotify
    watches per server to ~5.8k. That matters because the limit
    (``fs.inotify.max_user_watches``, 65536 by default) is per *user*, shared
    with the developer's editor — at the wide count a third warm server
    already fails to start, which ``hoot-shard -j 6`` would hit every run.

    Deliberately NOT used by the watchdog backend, which pays per *scheduled
    path* rather than per watched directory — see :class:`FSWatcherWatchdog`.
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
            for kind in ("src", "tests"):
                tree = addon / "static" / kind
                if tree.is_dir():
                    paths.append(str(tree))
    return paths


class FSWatcherBase:
    """Common file-change handler for both backends.

    Compiles the changed file as a syntax check before reloading: a
    syntax-broken file would crash the new server, leaving no running instance.
    Log and skip instead.
    """

    _reload_triggered = False

    def handle_asset_file(self, path: str) -> None:
        """Invalidate the assets cache of every database this server serves.

        This is the causal signal the asset caches were missing. Without it the
        only way to keep them correct across a file edit was to not use them —
        which is what ``--dev=xml`` does, at a measured 4.5x on every render —
        or to infer "the sources changed" from "a rebuild produced a different
        artifact", which throws away the entry the same request just computed.
        Watching the sources says it directly, so the caches can stay on.

        Propagation goes through the signalling table rather than through an
        in-memory ``clear_cache``. Under ``--workers`` this thread runs in the
        prefork master, which serves no request and — threads not surviving
        ``fork`` — shares no registry with its children: clearing in place
        reached nobody, and the workers went on answering the same URL with
        different bundles depending on which one replied. Writing the row
        instead reaches every process through ``Registry.check_signaling``,
        which ``http/_serve.py`` runs at the start of each request, i.e.
        exactly when a stale bundle would otherwise be served. The previous
        bundle URL stays live for pages already loaded until
        ``IrAttachment._gc_esm_assets`` sweeps it a grace window later.
        """
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
        """Route a changed file: asset sources invalidate, Python reloads."""
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
    """Cross-platform fallback using the ``watchdog`` library.

    Watches the addons roots whole in every mode, and lets ``handle_file``
    discard what it does not care about — the opposite of the inotify backend,
    on purpose. ``watchdog`` spends one *emitter thread pair and one inotify
    instance per scheduled path*, not per directory, so handing it the narrowed
    ``static/{src,tests}`` list (910 paths here) would ask for 910 instances
    against an ``fs.inotify.max_user_instances`` of 128 — measured to fail at
    50 — and ~1820 threads. Roots cost 6 instances, whatever the mode.
    """

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
    """POSIX inotify backend — no polling, kernel-level events."""

    def __init__(self) -> None:
        self.started = False
        self.thread: threading.Thread | None = None
        inotify.adapters._LOGGER.setLevel(logging.ERROR)
        paths_to_watch = inotify_watch_paths()
        _logger.info("Watching %d folder(s) for changes", len(paths_to_watch))
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
