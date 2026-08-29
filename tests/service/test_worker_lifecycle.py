import contextlib
import errno
import os
import pathlib
import resource
import socket
from unittest.mock import MagicMock, patch

import pytest

from odoo.service import _worker


def _open_fds() -> set[int]:
    return {
        int(entry.name)
        for entry in pathlib.Path("/proc/self/fd").iterdir()
        if entry.name.isdigit()
    }


@pytest.fixture
def multi():
    made = []

    def pipe_new():
        pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        made.append(pipe)
        return pipe

    m = MagicMock()
    m.pipe_new.side_effect = pipe_new
    m.timeout = 60
    m.beat = 4
    m.socket = None
    yield m
    for pipe in made:
        for fd in pipe:
            with contextlib.suppress(OSError):
                os.close(fd)


class TestWorkerConstructionIsAllOrNothing:
    def test_a_failed_second_pipe_closes_the_first(self, multi):
        opened = []

        def one_then_fail():
            if opened:
                raise OSError(errno.EMFILE, "too many open files")
            pipe = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            opened.append(pipe)
            return pipe

        multi.pipe_new.side_effect = one_then_fail
        before = _open_fds()

        with pytest.raises(OSError):
            _worker.Worker(multi)

        assert _open_fds() <= before, (
            f"the watchdog pipe survived a failed construction: "
            f"{sorted(_open_fds() - before)}. The master retries the spawn, so "
            f"this leaks two descriptors per attempt — under EMFILE, which is "
            f"the condition that caused it"
        )

    def test_a_successful_construction_keeps_both_pipes(self, multi):
        worker = _worker.Worker(multi)
        assert len(set(worker.watchdog_pipe) | set(worker.eintr_pipe)) == 4
        assert worker.wakeup_fd_r, worker.wakeup_fd_w == worker.eintr_pipe
        worker.close()

    def test_close_releases_every_descriptor_it_took(self, multi):
        before = _open_fds()
        worker = _worker.Worker(multi)
        assert len(_open_fds() - before) == 4
        worker.close()
        assert _open_fds() <= before

    def test_close_is_idempotent(self, multi):
        worker = _worker.Worker(multi)
        worker.close()
        worker.close()


class TestWorkerSignalDispositions:
    def test_a_quit_signal_only_clears_alive(self, multi):
        worker = _worker.Worker(multi)
        worker.alive = True
        worker.signal_handler(2, None)
        assert worker.alive is False, (
            "the handler must not do the teardown itself: it runs on whatever "
            "stack the signal interrupted"
        )
        worker.close()

    def test_the_cpu_alarm_raises_and_names_the_limit(self, multi):
        worker = _worker.Worker(multi)
        with (
            patch.object(_worker, "config", {"limit_time_cpu": 77}),
            pytest.raises(_worker.CpuTimeLimitExceeded, match="77"),
        ):
            worker.signal_time_expired_handler(24, None)
        worker.close()


class TestCpuRlimitClamp:
    def _apply(self, multi, *, hard, cpu_used=10.0, limit=60):
        worker = _worker.Worker(multi)
        worker.ppid = os.getppid()
        worker.alive = True
        worker.request_max = 0
        worker.request_count = 0
        worker._process_handle = MagicMock()
        res = MagicMock()
        res.RLIM_INFINITY = resource.RLIM_INFINITY
        res.getrusage.return_value = MagicMock(ru_utime=cpu_used, ru_stime=0.0)
        res.getrlimit.return_value = (resource.RLIM_INFINITY, hard)
        with (
            patch.object(_worker, "resource", res),
            patch.object(
                _worker, "config", {"limit_memory_soft": 0, "limit_time_cpu": limit}
            ),
            patch.object(_worker, "over_memory_soft_limit", return_value=None),
        ):
            worker.check_limits()
        worker.close()
        return res.setrlimit.call_args.args[1]

    def test_the_soft_limit_is_now_plus_the_budget(self, multi):
        soft, _hard = self._apply(multi, hard=resource.RLIM_INFINITY)
        assert soft == 70, "10s already burned plus a 60s budget"

    def test_it_is_clamped_to_the_hard_ceiling(self, multi):
        soft, hard = self._apply(multi, hard=65)
        assert (soft, hard) == (65, 65), (
            "setrlimit raises ValueError when soft exceeds hard, and this runs "
            "on every check_limits pass — so an unclamped value does not cap "
            "CPU, it kills the worker with a traceback"
        )

    def test_an_infinite_ceiling_is_not_treated_as_a_small_number(self, multi):
        soft, _hard = self._apply(multi, hard=resource.RLIM_INFINITY, cpu_used=1e6)
        assert soft == 1e6 + 60, (
            "RLIM_INFINITY is -1 on Linux, so comparing against it numerically "
            "would clamp every worker to a soft limit of -1"
        )


@pytest.fixture
def started(multi):
    worker = _worker.Worker(multi)
    signal_mod, selectors_mod, psutil_mod, fcntl_mod = (MagicMock() for _ in range(4))
    signal_mod.SIG_DFL = "SIG_DFL"
    with (
        patch.object(_worker, "signal", signal_mod),
        patch.object(_worker, "selectors", selectors_mod),
        patch.object(_worker, "psutil", psutil_mod),
        patch.object(_worker, "fcntl", fcntl_mod),
    ):
        worker.logger = MagicMock()
        worker.start()
        yield worker, signal_mod, selectors_mod, fcntl_mod
    worker.close()


class TestWorkerStart:
    def test_the_quit_and_cpu_signals_get_handlers(self, started):
        worker, signal_mod, _, _ = started
        installed = {
            call.args[0]: call.args[1] for call in signal_mod.signal.call_args_list
        }
        assert installed[signal_mod.SIGINT] == worker.signal_handler
        assert installed[signal_mod.SIGXCPU] == worker.signal_time_expired_handler

    def test_the_masters_own_signals_are_reset_to_default(self, started):
        _, signal_mod, _, _ = started
        installed = {
            call.args[0]: call.args[1] for call in signal_mod.signal.call_args_list
        }
        for name in ("SIGTERM", "SIGHUP", "SIGCHLD", "SIGTTIN", "SIGTTOU"):
            assert installed[getattr(signal_mod, name)] == "SIG_DFL", (
                f"the child inherited the master's {name} disposition; a "
                f"worker that handles SIGCHLD or SIGHUP acts on events meant "
                f"for the master"
            )

    def test_the_wakeup_fd_is_the_workers_own_eintr_pipe(self, started):
        worker, signal_mod, _, _ = started
        signal_mod.set_wakeup_fd.assert_called_once_with(worker.wakeup_fd_w)

    def test_the_selector_watches_that_pipe(self, started):
        worker, _, selectors_mod, _ = started
        selector = selectors_mod.DefaultSelector.return_value
        assert selector.register.call_args.args[0] == worker.wakeup_fd_r

    def test_a_listening_socket_is_marked_cloexec_and_non_blocking(self, multi):
        sock = socket.socket()
        sock.set_inheritable(True)
        multi.socket = sock
        worker = _worker.Worker(multi)
        worker.logger = MagicMock()
        with (
            patch.object(_worker, "signal", MagicMock()),
            patch.object(_worker, "selectors", MagicMock()),
            patch.object(_worker, "psutil", MagicMock()),
        ):
            worker.start()
        assert sock.getblocking() is False, (
            "a blocking accept() in a worker cannot be interrupted by the "
            "watchdog, so the master can only SIGKILL it"
        )
        assert os.get_inheritable(sock.fileno()) is False, (
            "without FD_CLOEXEC the listen socket survives into every "
            "subprocess the worker spawns, which keeps the port bound after a "
            "shutdown"
        )
        worker.close()
        sock.close()


class TestWorkerStop:
    def test_it_closes_the_selector(self, started):
        worker, _, selectors_mod, _ = started
        worker.stop()
        selectors_mod.DefaultSelector.return_value.close.assert_called_once()

    def test_stopping_a_worker_that_never_started_is_not_an_error(self, multi):
        worker = _worker.Worker(multi)
        worker.stop()
        worker.close()


class TestWorkerHttpAcceptErrors:
    def _process(self, multi, exc):
        worker = object.__new__(_worker.WorkerHTTP)
        worker.multi = multi
        multi.socket = MagicMock()
        multi.socket.accept.side_effect = exc
        worker.process_request = MagicMock()
        return worker

    @pytest.mark.parametrize("code", [errno.EAGAIN, errno.ECONNABORTED])
    def test_routine_accept_failures_are_swallowed(self, multi, code):
        worker = self._process(multi, OSError(code, "transient"))
        worker.process_work()
        worker.process_request.assert_not_called()

    def test_anything_else_propagates(self, multi):
        worker = self._process(multi, OSError(errno.EMFILE, "too many open files"))
        with pytest.raises(OSError, match="too many open files"):
            worker.process_work()

    def test_a_successful_accept_is_handed_on(self, multi):
        worker = object.__new__(_worker.WorkerHTTP)
        worker.multi = multi
        client, addr = MagicMock(), ("127.0.0.1", 5555)
        multi.socket = MagicMock()
        multi.socket.accept.return_value = (client, addr)
        worker.process_request = MagicMock()
        worker.process_work()
        worker.process_request.assert_called_once_with(client, addr)
