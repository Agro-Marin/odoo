"""Pure-pytest tests for ``odoo.service._watcher`` — the ``--dev`` autoreloader.

Two distinct jobs, both silent when broken:

* ``handle_file`` restarts the server when a watched ``.py`` changes;
* ``handle_asset_file`` writes the assets signalling row so every process
  invalidates its bundle caches on the next request.

Failure in either is invisible by construction — under ``--dev=assets`` the
server keeps serving the PREVIOUS bundle rather than erroring, so a green test
run proves nothing about an edit.  That is why the inotify class below drives a
real kernel watch instead of a mock.

Moved out of ``test_server.py``: the subject is ``_watcher``, and that file had
grown to 60 classes across 11 modules.  The same reasoning already moved
``TestAdminGates`` into ``test_db.py``.

Run with::

    python -m pytest tests/service/test_watcher.py -v
"""

import errno
import shutil
import time
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from odoo.service import _watcher


@pytest.fixture(scope="module")
def srv():
    """The module under test.

    Named ``srv`` because these classes were written against the
    ``odoo.service.server`` façade, which re-exports every name used here from
    ``_watcher`` — the same objects, so the tests are unchanged by the move.
    """
    return _watcher


class TestFSWatcherBase:
    """``FSWatcherBase.handle_file(path)``: validates Python syntax, triggers reload."""

    @pytest.fixture
    def watcher(self, srv):
        return srv.FSWatcherBase()

    @pytest.fixture(autouse=True)
    def _reload_enabled(self):
        """``handle_file`` returns None before any of its own logic unless
        ``reload`` is in ``dev_mode``, so without this every test below passes
        vacuously — including the negative ones.
        """
        import odoo.tools

        with odoo.tools.config.patch(dev_mode=["reload"]):
            yield

    def test_valid_py_triggers_restart(self, watcher, tmp_path):
        py = tmp_path / "good.py"
        py.write_text("x = 1 + 1\n")
        # ``handle_file`` and ``_trigger_restart`` lazy-import
        # ``server_phoenix`` and ``restart`` from ``odoo.service.lifecycle``
        # (the single source of truth), so the patch must target that module.
        with (
            patch("odoo.service.lifecycle.server_phoenix", False),
            patch("odoo.service.lifecycle.restart") as mock_restart,
        ):
            result = watcher.handle_file(str(py))
        mock_restart.assert_called_once()
        assert result is True

    def test_second_change_does_not_trigger_a_second_restart(self, watcher, tmp_path):
        """One reload per watcher, latched in the base class.

        ``lifecycle.server_phoenix`` is the authoritative "already reloading"
        flag, but ``restart()`` only SENDS the signal — the flag is set later,
        by the SIGHUP handler on the main thread.  A burst of saves (an IDE
        writing several files, a ``git checkout``) therefore raced that window.
        ``FSWatcherInotify`` happened to be safe because its loop ends on the
        ``True`` return; ``FSWatcherWatchdog.dispatch`` discards the return
        value, so it kept firing.  The latch makes both correct by construction.
        """
        a, b = tmp_path / "a.py", tmp_path / "b.py"
        a.write_text("x = 1\n")
        b.write_text("y = 2\n")
        with (
            patch("odoo.service.lifecycle.server_phoenix", False),
            patch("odoo.service.lifecycle.restart") as mock_restart,
        ):
            first = watcher.handle_file(str(a))
            second = watcher.handle_file(str(b))
        assert first is True
        assert second is None
        mock_restart.assert_called_once()

    def test_syntax_error_suppresses_restart(self, watcher, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def (\n")
        with patch("odoo.service.lifecycle.restart") as mock_restart:
            result = watcher.handle_file(str(bad))
        mock_restart.assert_not_called()
        assert result is None

    def test_missing_file_suppresses_restart(self, watcher, tmp_path):
        """OSError (e.g. file deleted between discovery and read) must not crash."""
        with patch("odoo.service.lifecycle.restart") as mock_restart:
            result = watcher.handle_file(str(tmp_path / "ghost.py"))
        mock_restart.assert_not_called()
        assert result is None

    def test_non_py_file_is_ignored(self, watcher, tmp_path):
        txt = tmp_path / "config.yaml"
        txt.write_text("key: value")
        with patch("odoo.service.lifecycle.restart") as mock_restart:
            result = watcher.handle_file(str(txt))
        mock_restart.assert_not_called()
        assert result is None

    def test_hidden_tilde_py_file_is_ignored(self, watcher, tmp_path):
        """Files whose names start with ``.~`` are editor swap files; skip them."""
        hidden = tmp_path / ".~mymodule.py"
        hidden.write_text("pass\n")
        with patch("odoo.service.lifecycle.restart") as mock_restart:
            result = watcher.handle_file(str(hidden))
        mock_restart.assert_not_called()
        assert result is None

    def test_server_phoenix_skips_restart(self, watcher, tmp_path):
        """When a reload is already in progress, do not trigger a second restart."""
        py = tmp_path / "ok.py"
        py.write_text("pass\n")
        with (
            patch("odoo.service.lifecycle.server_phoenix", True),
            patch("odoo.service.lifecycle.restart") as mock_restart,
        ):
            result = watcher.handle_file(str(py))
        mock_restart.assert_not_called()
        assert result is None


# ---------------------------------------------------------------------------
# FSWatcherBase.handle_asset_file() — the invalidation itself
# ---------------------------------------------------------------------------


class TestFSWatcherAssetInvalidation:
    """``handle_asset_file`` writes the assets signalling row for every served
    database, so ``Registry.check_signaling`` invalidates the bundle caches on
    the next request in every process.

    The burst-coalescing tests further down patch this method out to count
    calls, so the body itself — which databases it reaches, and what happens
    when one of them is unreachable — ran in no test.  Failure here is silent
    by construction: the server keeps serving the *previous* bundle rather than
    erroring, which is exactly what makes a green test run prove nothing about
    an edit under ``--dev=assets``.
    """

    @pytest.fixture
    def invalidate(self, srv):
        def _run(*, registries=(), configured=(), failing=()):
            import odoo.db
            import odoo.orm.runtime.registry as registry_mod
            import odoo.tools

            statements = []

            def db_connect(db_name):
                if db_name in failing:
                    raise psycopg.OperationalError(f"{db_name} is unreachable")
                cursor = MagicMock()
                cursor.__enter__ = MagicMock(return_value=cursor)
                cursor.__exit__ = MagicMock(return_value=None)
                cursor.execute.side_effect = lambda sql, *a: statements.append(
                    (db_name, sql)
                )
                handle = MagicMock()
                handle.cursor.return_value = cursor
                return handle

            fake_registry = MagicMock()
            fake_registry.registries.snapshot = list(registries)
            watcher = srv.FSWatcherBase()
            with (
                patch.object(odoo.db, "db_connect", db_connect),
                patch.object(registry_mod, "Registry", fake_registry),
                patch.object(odoo.tools, "config", {"db_name": list(configured)}),
            ):
                watcher.handle_asset_file("/src/some_bundle.js")
            return statements

        return _run

    def test_signals_loaded_and_configured_databases(self, invalidate):
        """Both sources matter: a registry may be loaded without being listed in
        ``db_name``, and a configured database may not have been loaded yet."""
        statements = invalidate(registries=["loaded"], configured=["configured"])
        assert {db for db, _ in statements} == {"loaded", "configured"}

    def test_each_database_is_signalled_once(self, invalidate):
        """A database present in both sources must not be signalled twice — the
        insert is a round-trip on the watcher thread, and this runs per file."""
        statements = invalidate(registries=["shared"], configured=["shared"])
        assert len(statements) == 1

    def test_the_statement_is_the_assets_signal(self, invalidate):
        statements = invalidate(registries=["db1"])
        assert "orm_signaling_assets" in statements[0][1]

    def test_an_unreachable_database_does_not_stop_the_others(self, invalidate):
        """A stopped or dropped database is ordinary in development.  If it
        aborted the loop, every database ordered after it would keep serving a
        stale bundle for the rest of the process's life, with nothing but a log
        line to say so.
        """
        statements = invalidate(
            registries=["alpha", "broken", "omega"], failing=["broken"]
        )
        assert {db for db, _ in statements} == {"alpha", "omega"}

    def test_a_total_outage_is_swallowed_not_raised(self, invalidate):
        """This runs on the watcher thread; an escaping exception kills the
        watcher and silently ends reloading for the rest of the session."""
        assert invalidate(registries=["a", "b"], failing=["a", "b"]) == []


# ---------------------------------------------------------------------------
# PreforkServer.process_signals()
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    __import__("odoo.service._watcher", fromlist=["inotify"]).inotify is None,
    reason="inotify backend not installed",
)
class TestFSWatcherInotifyRewatch:
    """A subtree moved in whole must be watched down to its leaves.

    ``_BaseTree.event_gen`` already re-watches the directory named by an
    ``IN_CREATE`` / ``IN_MOVED_TO`` event, so directories that appear one level
    at a time are covered. A *rename* is different: the kernel reports one
    event for the subtree root, and every directory nested inside it arrives
    already-populated and unwatched. Odoo then walked that subtree for its
    files but never watched it, so the walk saw each file exactly once and
    every later edit below the first level was invisible.

    That is the shape a branch switch produces, and it is silent: under
    ``--dev=assets`` the server keeps serving the previous bundle rather than
    reporting an error, so a green test run proves nothing about the edit.
    """

    @pytest.fixture
    def watcher(self, tmp_path):
        from odoo.service import _watcher as w

        root = tmp_path / "watched"
        root.mkdir()
        seen = []
        obj = w.FSWatcherInotify.__new__(w.FSWatcherInotify)
        obj.started = False
        obj.thread = None
        # Production builder, so the test covers what __init__ actually sets up
        # (notably the overflow watch-descriptor mapping) rather than a copy.
        try:
            obj._build_watcher([str(root)], block_duration_s=0.05)
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                raise
            # A per-USER cap, not a property of this checkout: every concurrent
            # server, test run and editor holds inotify instances from the same
            # pool. Erroring here reported a defect in the watcher whenever the
            # box was merely busy, and did it behind "No space left on device",
            # which is why the class read as flaky. Skip on the one errno that
            # means "the OS would not give us the resource", never on any other.
            pytest.skip(str(exc))
        obj.handle_file = lambda path: seen.append(path) and None
        obj.start()
        try:
            yield obj, seen, root
        finally:
            obj.started = False
            # Unblock event_gen so the loop can observe ``started`` and exit.
            (root / "_wake").write_text("x")
            if obj.thread is not None:
                obj.thread.join(timeout=5)

    @staticmethod
    def _wait_for(predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def _staging_tree(tmp_path):
        """A populated nested tree built outside the watched root, so that
        moving it in produces a single ``IN_MOVED_TO`` for its top directory."""
        staging = tmp_path / "staging"
        (staging / "utils" / "dnd").mkdir(parents=True)
        (staging / "top.js").write_text("export const T = 1;\n")
        (staging / "utils" / "mid.js").write_text("export const M = 1;\n")
        (staging / "utils" / "dnd" / "leaf.js").write_text("export const L = 1;\n")
        return staging

    def test_nested_directory_of_a_moved_subtree_is_watched(self, watcher, tmp_path):
        obj, _seen, root = watcher
        staging = self._staging_tree(tmp_path)
        moved = root / "moved_subtree"
        staging.rename(moved)

        watches = lambda: getattr(obj.watcher._i, "_Inotify__watches", {})  # noqa: E731
        assert self._wait_for(lambda: str(moved) in watches()), (
            "subtree root was never watched"
        )
        for nested in (moved / "utils", moved / "utils" / "dnd"):
            assert self._wait_for(lambda n=nested: str(n) in watches()), (
                f"nested directory {nested} of a moved subtree was never watched"
            )

    def test_edit_below_the_first_level_of_a_moved_subtree_is_seen(
        self, watcher, tmp_path
    ):
        """The regression proper: the walk reports each file once, so only a
        watch on the nested directory can report a *later* edit."""
        _obj, seen, root = watcher
        staging = self._staging_tree(tmp_path)
        moved = root / "moved_subtree"
        staging.rename(moved)

        leaf = moved / "utils" / "dnd" / "leaf.js"
        assert self._wait_for(lambda: str(leaf) in seen), "initial walk missed the leaf"
        seen.clear()

        leaf.write_text("export const L = 2;\n")
        assert self._wait_for(lambda: str(leaf) in seen), (
            f"edit below the first level of a moved subtree went unseen; saw {seen}"
        )

    def test_directory_recreated_at_a_reaped_path_is_rearmed(self, watcher, tmp_path):
        """A branch switch and back: the kernel reaps the watch when the
        directory goes away, but ``IN_MOVED_FROM`` / ``IN_IGNORED`` are outside
        the effective mask, so the library keeps listing the path and
        ``add_watch`` then arms nothing. Left alone the directory is unwatched
        for the rest of the process's life."""

        obj, seen, root = watcher
        sub = root / "toggled"
        sub.mkdir()
        assert self._wait_for(
            lambda: str(sub) in getattr(obj.watcher._i, "_Inotify__watches", {})
        ), "directory was never watched on first creation"

        shutil.rmtree(sub)
        sub.mkdir()

        # Barrier: both this file and the mkdir above are events on the *root*
        # watch, and inotify delivers a watch's events in order, so seeing it
        # proves the recreation has already been processed. Without this the
        # run loop can still be walking the new directory when the target file
        # lands, and the walk reports it -- passing the test for the wrong
        # reason, whether or not the watch was ever re-armed.
        barrier = root / "_barrier.js"
        barrier.write_text("export const B = 1;\n")
        assert self._wait_for(lambda: str(barrier) in seen), "run loop never caught up"
        seen.clear()

        target = sub / "after_recreate.js"
        target.write_text("export const D = 1;\n")
        assert self._wait_for(lambda: str(target) in seen), (
            f"edit in a recreated directory went unseen; saw {seen}"
        )

    def test_overflow_watch_descriptor_is_mapped(self, watcher):
        """Without this the overflow event is unreachable: it carries
        ``wd == -1``, the library looks that up in its reverse map, misses, and
        drops the event -- so a queue that discarded 13616 of 30000 events (the
        measured figure at ``max_queued_events`` 16384) looks exactly like a
        quiet tree."""
        from odoo.service import _watcher as w

        obj, _seen, _root = watcher
        assert (
            getattr(obj.watcher._i, "_Inotify__watches_r", {}).get(w.OVERFLOW_WD)
            == w.OVERFLOW_PATH
        )

    def test_run_resyncs_on_overflow_and_re_raises_other_terminal_events(self):
        """The library ends the generator on any terminal event. Overflow is
        recoverable -- the queue drains and delivery resumes -- so ``run`` has
        to resync and re-enter; leaving the thread dead would strand a live
        server with a watcher that reports nothing, which is the failure this
        whole class exists to prevent."""
        from odoo.service import _watcher as w

        def _watcher_raising(type_name):
            class _W:
                def event_gen(self, **kwargs):
                    raise w.TerminalEventException(type_name, None)
                    yield  # pragma: no cover - generator marker

            return _W()

        obj = w.FSWatcherInotify.__new__(w.FSWatcherInotify)
        obj.started = True
        obj.watcher = _watcher_raising("IN_Q_OVERFLOW")
        calls = []

        def _resync():
            calls.append(1)
            obj.started = False  # let the loop exit once recovery is observed

        obj._resync = _resync
        obj.run()
        assert calls == [1], "overflow did not trigger a resync"

        obj.started = True
        obj.watcher = _watcher_raising("IN_UNMOUNT")
        with pytest.raises(w.TerminalEventException):
            obj.run()

    def test_asset_burst_signals_twice_not_once_per_file(self, watcher):
        """One round-trip per file per database (measured 1.64 ms) caps this
        thread near 610 events/s, which is what lets the kernel queue overrun
        during a branch switch. Leading edge keeps a single edit as prompt as
        before; the rest of the burst collapses into one trailing signal."""
        obj, _seen, _root = watcher
        from odoo.service._watcher import FSWatcherBase

        inserts = []
        with patch.object(
            FSWatcherBase, "handle_asset_file", lambda self, path: inserts.append(path)
        ):
            for i in range(50):
                obj.handle_asset_file(f"/x/f{i}.js")
            assert len(inserts) == 1, "leading edge did not fire exactly once"
            obj._end_burst()
            assert len(inserts) == 2, "trailing flush did not fire"
            obj._end_burst()
            assert len(inserts) == 2, "idle with nothing pending still signalled"

    def test_edit_after_the_leading_edge_is_still_signalled(self, watcher):
        """The property the whole coalescing hinges on: a file changed *after*
        the leading insert must still produce one. Dropping it would recreate
        the stale-bundle failure this class exists to prevent."""
        obj, _seen, _root = watcher
        from odoo.service._watcher import FSWatcherBase

        inserts = []
        with patch.object(
            FSWatcherBase, "handle_asset_file", lambda self, path: inserts.append(path)
        ):
            obj.handle_asset_file("/x/first.js")
            assert len(inserts) == 1
            obj.handle_asset_file("/x/second.js")  # arrives after the insert
            assert len(inserts) == 1, "should be pending, not immediate"
            obj._end_burst()
            assert len(inserts) == 2, "the later edit was never signalled"

    def test_a_single_edit_still_signals_immediately(self, watcher):
        """No latency regression for the edit/run loop: the first change in a
        quiet period must not wait for the idle tick."""
        obj, _seen, _root = watcher
        from odoo.service._watcher import FSWatcherBase

        inserts = []
        with patch.object(
            FSWatcherBase, "handle_asset_file", lambda self, path: inserts.append(path)
        ):
            obj.handle_asset_file("/x/only.js")
            assert len(inserts) == 1, "single edit was deferred to the idle tick"
