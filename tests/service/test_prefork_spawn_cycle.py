import contextlib
import os
import signal
from unittest.mock import MagicMock, patch

import pytest

from odoo.service import _prefork


@pytest.fixture
def prefork():
    obj = object.__new__(_prefork.PreforkServer)
    obj.population = 2
    obj.logger = MagicMock()
    obj.workers = {}
    obj.workers_http = {}
    obj.workers_cron = {}
    obj.workers_job = {}
    obj.long_polling_pid = None
    obj._consecutive_fast_deaths = 0
    obj._respawn_not_before = 0.0
    obj.queue = []
    obj._selector = None
    obj.pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    yield obj
    obj._close_watchdog_selector()
    for fd in obj.pipe:
        with contextlib.suppress(OSError):
            os.close(fd)


class TestSignalHandlerCoalescesSigchld:
    def test_repeated_sigchld_enqueues_once(self, prefork):
        for _ in range(5):
            prefork.signal_handler(signal.SIGCHLD, None)
        assert prefork.queue == [signal.SIGCHLD], (
            "SIGCHLD must be coalesced: the master reaps every zombie in one "
            "process_zombie() pass, so N deaths need one queue entry, not N"
        )

    def test_a_second_sigchld_after_the_queue_drains_is_enqueued_again(self, prefork):
        prefork.signal_handler(signal.SIGCHLD, None)
        prefork.queue.clear()
        prefork.signal_handler(signal.SIGCHLD, None)
        assert prefork.queue == [signal.SIGCHLD]

    def test_other_signals_are_not_coalesced(self, prefork):
        prefork.signal_handler(signal.SIGHUP, None)
        prefork.signal_handler(signal.SIGHUP, None)
        assert prefork.queue == [signal.SIGHUP, signal.SIGHUP], (
            "two SIGHUPs are two reload requests; collapsing them drops one"
        )

    def test_every_signal_wakes_the_select_loop(self, prefork):
        prefork.signal_handler(signal.SIGTERM, None)
        assert os.read(prefork.pipe[0], 8) == b".", (
            "the handler must ping the self-pipe or sleep() blocks until its "
            "next timeout instead of acting on the signal"
        )

    def test_a_full_pipe_is_not_an_error(self, prefork):
        try:
            while True:
                os.write(prefork.pipe[1], b"." * 4096)
        except BlockingIOError:
            pass
        prefork.signal_handler(signal.SIGCHLD, None)
        assert prefork.queue == [signal.SIGCHLD]


def _fake_worker():
    w = MagicMock()
    w.watchdog_pipe = os.pipe()
    w.eintr_pipe = os.pipe()
    return w


def _is_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


class TestChildClosesInheritedFds:
    def test_a_sibling_worker_pipes_are_closed(self, prefork):
        sibling = _fake_worker()
        newborn = _fake_worker()
        prefork.workers = {111: sibling}
        prefork._close_inherited_pipe_fds_in_child(newborn)
        sibling_fds = [*sibling.watchdog_pipe, *sibling.eintr_pipe]
        assert not any(_is_open(fd) for fd in sibling_fds), (
            f"the child kept a sibling's pipe fds open {sibling_fds}: the "
            "sibling's reader never sees EOF when that worker dies"
        )
        for fd in (*newborn.watchdog_pipe, *newborn.eintr_pipe):
            assert _is_open(fd), "the child closed its OWN watchdog/eintr pipe"
            os.close(fd)

    def test_the_masters_own_self_pipe_is_closed(self, prefork):
        newborn = _fake_worker()
        master_pipe = prefork.pipe
        prefork._close_inherited_pipe_fds_in_child(newborn)
        assert not any(_is_open(fd) for fd in master_pipe), (
            "the child inherited the master's signal self-pipe; a signal "
            "delivered to the child would ping the master's select loop"
        )
        prefork.pipe = os.pipe2(os.O_NONBLOCK)
        for fd in (*newborn.watchdog_pipe, *newborn.eintr_pipe):
            os.close(fd)

    def test_closing_an_already_closed_fd_is_tolerated(self, prefork):
        sibling = _fake_worker()
        prefork.workers = {111: sibling}
        os.close(sibling.watchdog_pipe[0])
        newborn = _fake_worker()
        prefork._close_inherited_pipe_fds_in_child(newborn)
        for fd in (*newborn.watchdog_pipe, *newborn.eintr_pipe):
            os.close(fd)


class TestProcessSpawnChecksSignallingOncePerCycle:
    def _run(self, prefork, registries, cfg):
        spawned = []

        def fake_spawn(klass, registry):
            worker = MagicMock()
            pid = 1000 + len(spawned)
            spawned.append(klass.__name__)
            registry[pid] = worker
            prefork.workers[pid] = worker
            return worker

        snapshot = MagicMock()
        snapshot.snapshot = registries
        with (
            patch.object(_prefork, "config", cfg),
            patch.object(_prefork.Registry, "registries", snapshot),
            patch.object(_prefork, "db") as fake_db,
            patch.object(prefork, "worker_spawn", side_effect=fake_spawn),
            patch.object(prefork, "long_polling_spawn"),
        ):
            prefork.process_spawn()
        return spawned, fake_db

    def test_signalling_is_checked_once_no_matter_how_many_workers_spawn(self, prefork):
        checks = []
        registry = MagicMock()
        registry.check_signaling.side_effect = checks.append
        cfg = {"http_enable": True, "max_cron_threads": 2, "job_workers": 2}
        prefork.population = 4

        spawned, _ = self._run(prefork, {"db1": registry}, cfg)

        assert len(spawned) == 8, spawned
        assert len(checks) == 1, (
            f"check_signaling ran {len(checks)} times for one spawn cycle that "
            f"forked {len(spawned)} workers; it must run once, before the first "
            "fork, so no child inherits a stale registry and none pays for a "
            "redundant round trip"
        )

    def test_the_live_registry_cache_is_never_emptied(self, prefork):
        registries = {"db1": MagicMock()}
        cfg = {"http_enable": False, "max_cron_threads": 1, "job_workers": 0}
        self._run(prefork, registries, cfg)
        assert registries == {"db1": registries["db1"]}, (
            "process_spawn mutated the registry mapping it was handed; the "
            "snapshot is a copy today, but clearing it is the shape of the bug "
            "that made this read as emptying the server's live cache"
        )

    def test_no_registries_means_no_check_and_still_spawns(self, prefork):
        cfg = {"http_enable": False, "max_cron_threads": 1, "job_workers": 0}
        spawned, fake_db = self._run(prefork, {}, cfg)
        assert spawned == ["WorkerCron"]
        fake_db.close_all.assert_not_called()

    def test_a_registry_that_raises_does_not_abort_the_cycle(self, prefork):
        bad = MagicMock()
        bad.cursor.side_effect = RuntimeError("db gone")
        good = MagicMock()
        cfg = {"http_enable": False, "max_cron_threads": 2, "job_workers": 0}

        spawned, _ = self._run(prefork, {"bad": bad, "good": good}, cfg)

        assert spawned == ["WorkerCron", "WorkerCron"], (
            "one unreachable database stopped the master from spawning workers"
        )
        good.cursor.assert_called_once()

    def test_the_backoff_window_suppresses_the_whole_cycle(self, prefork):
        cfg = {"http_enable": True, "max_cron_threads": 2, "job_workers": 2}
        with patch.object(_prefork.time, "monotonic", return_value=100.0):
            prefork._respawn_not_before = 200.0
            spawned, _ = self._run(prefork, {"db1": MagicMock()}, cfg)
        assert spawned == [], (
            "process_spawn forked inside the respawn backoff window; a worker "
            "crash-looping at boot would be respawned as fast as it dies"
        )

    def test_a_failed_spawn_stops_the_cycle_instead_of_looping(self, prefork):
        cfg = {"http_enable": False, "max_cron_threads": 3, "job_workers": 2}
        with (
            patch.object(_prefork, "config", cfg),
            patch.object(_prefork.Registry, "registries", MagicMock(snapshot={})),
            patch.object(_prefork, "db"),
            patch.object(prefork, "worker_spawn", return_value=None) as spawn,
        ):
            prefork.process_spawn()
        assert spawn.call_count == 1, (
            f"worker_spawn returned None (fork failed) and process_spawn called "
            f"it {spawn.call_count} times in the same cycle. A fork that failed "
            f"with EAGAIN fails for every later class too, so the cycle must be "
            f"abandoned (return), not merely the current loop (break)."
        )


class TestTheWatchdogSelectorIsReused:
    """`sleep()` runs once per beat, and graceful stop drops the beat to 0.1s."""

    @pytest.fixture
    def master(self, prefork):
        prefork.beat = 0
        made = []

        def _add():
            w = MagicMock()
            w.watchdog_pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            w.watchdog_time = 0.0
            pid = len(made) + 1
            prefork.workers[pid] = w
            made.append(w)
            return pid, w

        yield prefork, _add
        for w in made:
            for fd in w.watchdog_pipe:
                with contextlib.suppress(OSError):
                    os.close(fd)

    def test_the_same_selector_serves_every_beat(self, master):
        prefork, add = master
        add()
        prefork.sleep()
        first = prefork._selector
        prefork.sleep()
        prefork.sleep()
        assert prefork._selector is first, (
            "a new epoll instance per beat; at the 0.1s shutdown beat that is "
            "ten create/teardown pairs a second"
        )

    def test_a_new_worker_is_picked_up_without_rebuilding(self, master):
        prefork, add = master
        prefork.sleep()
        first = prefork._selector
        _, w = add()
        prefork.sleep()
        assert prefork._selector is first
        assert w.watchdog_pipe[0] in set(prefork._selector.get_map())

    def test_a_reaped_worker_is_unregistered(self, master):
        prefork, add = master
        pid, w = add()
        prefork.sleep()
        del prefork.workers[pid]
        prefork.sleep()
        assert w.watchdog_pipe[0] not in set(prefork._selector.get_map())

    def test_the_masters_pipe_is_always_registered(self, master):
        prefork, add = master
        add()
        prefork.sleep()
        assert prefork.pipe[0] in set(prefork._selector.get_map())

    def test_the_forked_child_does_not_inherit_the_epoll_instance(self, master):
        prefork, _add = master
        prefork.sleep()
        assert prefork._selector is not None
        newborn = MagicMock()
        newborn.watchdog_pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        newborn.eintr_pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            prefork._close_inherited_pipe_fds_in_child(newborn)
        finally:
            for fds in (newborn.watchdog_pipe, newborn.eintr_pipe):
                for fd in fds:
                    with contextlib.suppress(OSError):
                        os.close(fd)
        assert prefork._selector is None, (
            "a worker never polls the master's watchdog set; carrying the "
            "epoll fd into the fork is one more descriptor per worker"
        )


class TestWatchdogSleep:
    @pytest.fixture
    def master(self, prefork):
        prefork.beat = 0
        made = []

        def _worker():
            w = MagicMock()
            w.watchdog_pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            w.watchdog_time = 0.0
            made.append(w)
            return w

        yield prefork, _worker
        for w in made:
            for fd in w.watchdog_pipe:
                with contextlib.suppress(OSError):
                    os.close(fd)

    def test_a_worker_that_pinged_has_its_clock_refreshed(self, master):
        prefork, make = master
        alive, quiet = make(), make()
        prefork.workers = {1: alive, 2: quiet}
        os.write(alive.watchdog_pipe[1], b".")

        prefork.sleep()

        assert alive.watchdog_time > 0.0, (
            "the worker said it was alive and the master did not record it; "
            "process_timeout will SIGKILL it once the beat elapses"
        )
        assert quiet.watchdog_time == 0.0, "a silent worker must not be credited"

    def test_the_ping_is_drained_so_the_next_select_blocks(self, master):
        prefork, make = master
        worker = make()
        prefork.workers = {1: worker}
        os.write(worker.watchdog_pipe[1], b"...")

        prefork.sleep()

        with pytest.raises(BlockingIOError):
            os.read(worker.watchdog_pipe[0], 8)

    def test_the_masters_own_pipe_is_watched_too(self, master):
        prefork, _ = master
        prefork.workers = {}
        os.write(prefork.pipe[1], b".")

        prefork.sleep()

        with pytest.raises(BlockingIOError):
            os.read(prefork.pipe[0], 8)

    def test_a_quiet_beat_credits_nobody(self, master):
        prefork, make = master
        worker = make()
        prefork.workers = {1: worker}
        prefork.sleep()
        assert worker.watchdog_time == 0.0


class TestRun:
    @pytest.fixture
    def running(self, prefork, monkeypatch):
        def _go(
            *,
            stop=False,
            preload_rc=0,
            ready_pid=None,
            loop_raises=None,
            kill_raises=None,
        ):
            calls = []
            for name in (
                "start",
                "process_signals",
                "process_zombie",
                "process_timeout",
                "process_spawn",
            ):
                setattr(
                    prefork, name, MagicMock(side_effect=lambda n=name: calls.append(n))
                )
            prefork.stop = MagicMock(side_effect=lambda *a: calls.append("stop"))
            prefork.sleep = MagicMock(side_effect=loop_raises or KeyboardInterrupt)
            monkeypatch.delenv("ODOO_READY_SIGHUP_PID", raising=False)
            if ready_pid is not None:
                monkeypatch.setenv("ODOO_READY_SIGHUP_PID", ready_pid)
            with (
                patch.object(_prefork, "preload_registries", return_value=preload_rc),
                patch.object(_prefork, "db") as fake_db,
                patch.object(_prefork.os, "kill", side_effect=kill_raises) as kill,
            ):
                rc = prefork.run(["db"], stop=stop)
            return rc, calls, kill, fake_db

        return _go

    def test_stop_after_init_returns_the_preload_code_without_serving(self, running):
        rc, calls, _, fake_db = running(stop=True, preload_rc=3)
        assert rc == 3
        assert calls == ["start", "stop"], calls
        assert not fake_db.close_all.called, (
            "closing the pools is preparation for forking workers; there are "
            "none on this path"
        )

    def test_serving_closes_the_pools_before_forking(self, running):
        _, calls, _, fake_db = running(stop=False)
        (
            fake_db.close_all.assert_called_once(),
            (
                "a connection open across fork() is shared by parent and child and "
                "corrupts both"
            ),
        )
        assert calls[0] == "start"

    def test_the_loop_runs_the_supervision_pass(self, running):
        _, calls, _, _ = running(stop=False)
        assert calls[1:5] == [
            "process_signals",
            "process_zombie",
            "process_timeout",
            "process_spawn",
        ], calls

    def test_a_keyboard_interrupt_is_a_clean_stop(self, running):
        rc, calls, _, _ = running(stop=False)
        assert rc is None
        assert calls[-1] == "stop"

    def test_an_uncaught_error_stops_forcefully_and_reports_minus_one(self, running):
        rc, calls, _, _ = running(stop=False, loop_raises=RuntimeError("boom"))
        assert rc == -1, "the master died; a zero exit tells the supervisor it meant to"
        assert calls[-1] == "stop"

    def test_a_system_exit_is_not_swallowed_by_the_catch_all(self, running):
        with pytest.raises(SystemExit):
            running(stop=False, loop_raises=SystemExit(2))

    def test_the_old_master_is_signalled_that_this_one_is_ready(self, running):
        _, _, kill, _ = running(stop=False, ready_pid="4242")
        kill.assert_called_once_with(4242, signal.SIGHUP)

    def test_the_handover_variable_is_consumed_not_inherited(self, running):
        running(stop=False, ready_pid="4242")
        assert "ODOO_READY_SIGHUP_PID" not in os.environ, (
            "left in the environment it is inherited by every worker fork, and "
            "each of them signals the old master again"
        )

    def test_an_unsignalable_old_master_is_a_warning_not_a_failure(self, running):
        rc, _calls, kill, _ = running(stop=False, ready_pid="not-a-pid")
        assert rc is None, (
            "the new server is up; failing the boot because the old one had "
            "already exited would be the one outcome worse than a stale process"
        )
        assert not kill.called

    def test_a_dead_old_master_is_also_survivable(self, running):
        rc, _, kill, _ = running(
            stop=False, ready_pid="999999", kill_raises=ProcessLookupError
        )
        assert rc is None, (
            "the old master exited on its own between handing over and being "
            "told to; there is nothing left to do and nothing wrong"
        )
        kill.assert_called_once()
