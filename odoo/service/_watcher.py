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

import odoo.addons

_logger = logging.getLogger("odoo.service.server")

_OBSERVER_JOIN_TIMEOUT_S = 5.0


ASSET_SUFFIXES = (".js", ".xml", ".scss", ".css")

OVERFLOW_WD = -1
"""Watch descriptor the kernel reports on ``IN_Q_OVERFLOW``; matches no watch."""

OVERFLOW_PATH = "<inotify-overflow>"
"""Stand-in path for the overflow event, which names no file."""

ASSET_BURST_PATH = "<asset-burst>"
"""Stand-in path for a coalesced invalidation, which covers many files."""


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

    _assets_dirty = False
    _burst_active = False

    def handle_asset_file(self, path: str) -> None:
        """Signal once per burst instead of once per file.

        The row is a monotonic counter that readers only ever compare, so N
        identical inserts and one carry the same meaning — but the insert is a
        database round-trip (measured 1.64 ms) *per file per database*, done on
        this thread, which caps it near 610 events/s. A branch switch across a
        few thousand assets therefore spends seconds here while the kernel keeps
        queueing, and events past ``max_queued_events`` are discarded: the
        watcher's own cost is what makes the overflow it must then recover from
        reachable.

        Leading edge fires immediately, so a single edit invalidates exactly as
        promptly as before; everything else in the burst only sets a flag, and
        :meth:`run` flushes it once the event stream goes idle — after every
        queued event has been read, so no edit can be left unsignalled.

        Only this backend coalesces: the flush needs an idle tick, and
        ``watchdog`` dispatches with no equivalent, so it keeps the immediate
        behaviour inherited from :class:`FSWatcherBase`.
        """
        self._assets_dirty = True
        if not self._burst_active:
            self._burst_active = True
            self._flush_asset_invalidation()

    def _flush_asset_invalidation(self) -> None:
        """Insert the pending signal, if any. Called on the leading edge and
        again once the stream goes idle."""
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
        """Build the watch tree and make queue overflows reportable.

        Kernel overflow events carry ``wd == -1``, which matches no watch, so
        the library's dispatch drops them before anything can react: the queue
        silently discards every event past ``fs.inotify.max_queued_events``
        (16384 here — 30000 writes yielded exactly 16384 events) and the server
        goes on believing it saw them. Naming that descriptor is what lets the
        event reach :meth:`run`, which turns it into a resync.
        """
        self.roots = paths
        self.watcher = InotifyTrees(
            paths, mask=INOTIFY_LISTEN_EVENTS, block_duration_s=block_duration_s
        )
        self.watcher._i._Inotify__watches_r[OVERFLOW_WD] = OVERFLOW_PATH

    def _resync(self) -> None:
        """Re-arm every watch and drop the asset caches after an event loss.

        An overflow gives no clue as to *what* was missed, so nothing narrower
        is sound: a directory created during the gap has no watch, and a file
        edited during it left no trace. Re-walking the roots restores the first,
        and one unconditional invalidation covers the second — expensive
        (~5.8k watches) but bounded, and only on an event the kernel reports at
        most once per burst.
        """
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
        """Watch one directory of a subtree that appeared after startup.

        ``_BaseTree.event_gen`` already re-watches the directory an
        ``IN_CREATE`` / ``IN_MOVED_TO`` event names, so a tree that grows one
        level at a time needs nothing more. A *rename* does: the kernel reports
        a single event for the subtree root, and every directory nested inside
        it arrives already-populated and unwatched. The walk below then visited
        those files exactly once, which is why the breakage is invisible — the
        first read after the move looks correct and every later edit is
        silently dropped.

        Under ``--dev=assets`` a dropped edit means the server goes on serving
        the previous bundle with no error at all, so a green test run says
        nothing about the code just written. Branch switches produce exactly
        this shape, and a warm server 19h old was measured holding 5570 watches
        against a fresh server's 5805, with edits under ``web/static/src`` no
        longer invalidating the assets cache while ``web/static/tests`` still
        did.

        Re-uses the tree's own augmented mask rather than
        :data:`INOTIFY_LISTEN_EVENTS`: ``_BaseTree`` adds ``IN_ISDIR |
        IN_CREATE | IN_DELETE`` so watches can curate themselves, and a watch
        missing those would not report its own subdirectories — reintroducing
        the same gap one level down.

        A path the library still lists is re-armed rather than trusted, because
        that listing is not evidence of a live watch. ``IN_MOVED_FROM`` and
        ``IN_IGNORED`` are both outside the effective mask, so the one branch
        that would drop the bookkeeping never runs: the kernel removes the watch
        when its directory goes away and the library goes on listing the path
        forever. ``add_watch`` then returns ``None`` for "already watched" and
        arms nothing, so a directory deleted and recreated at the same path —
        a branch switch and back — stays unwatched permanently.
        """
        path = str(directory)
        tree = self.watcher._i
        try:
            if tree.add_watch(path, self.watcher._mask) is not None:
                return
            # Listed but possibly dead. ``remove_watch`` drops the bookkeeping
            # before its syscall, so it clears the entry even when that syscall
            # fails on an already-reaped descriptor (``superficial`` is accepted
            # and then ignored by the library).
            try:
                tree.remove_watch(path, superficial=True)
            except Exception:
                _logger.debug("autoreload: stale watch purge for %s", path)
            tree.add_watch(path, self.watcher._mask)
        except Exception:
            _logger.warning(
                "autoreload: cannot watch %s; edits below it will not be seen "
                "(fs.inotify.max_user_watches exhausted?)",
                directory,
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
                # The library ends the generator on IN_Q_OVERFLOW / IN_UNMOUNT.
                # Overflow is recoverable — the queue drains and delivery
                # resumes — so resync and re-enter rather than leaving a live
                # server with a watcher thread that quietly died.
                if str(exc) != "IN_Q_OVERFLOW":
                    raise
                self._resync()
            # ``timeout_s=0`` makes the generator return once the current poll
            # cycle is drained, so this is the burst boundary: every event the
            # kernel had ready has been read, and anything still pending can be
            # signalled exactly once. Not ``yield_nones`` — that break happens
            # before its ``yield None``, so the idle tick never arrives and a
            # burst flag would latch on forever, suppressing every later signal.
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
