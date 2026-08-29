import errno
import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from odoo.service import wsgi


@pytest.fixture
def server():
    srv = object.__new__(wsgi.ThreadedWSGIServerReloadable)
    srv.max_http_threads = 0
    srv.daemon_threads = True
    return srv


@pytest.fixture
def bind(server, monkeypatch):
    def _run(*, listen_fds=None, listen_pid=None):
        for name, value in (("LISTEN_FDS", listen_fds), ("LISTEN_PID", listen_pid)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        adopted = MagicMock(name="adopted-socket")
        socket_mod = MagicMock(socket=MagicMock(return_value=adopted))
        own = MagicMock(name="its-own-socket")
        own.getsockname.return_value = ("127.0.0.1", 8069)
        server.socket = own
        server.server_address = ("127.0.0.1", 8069)
        server.allow_reuse_address = False
        server.allow_reuse_port = False
        server.address_family = 2
        with patch.object(wsgi, "socket", socket_mod):
            server.server_bind()
        return server, socket_mod, adopted, own

    return _run


class TestSocketActivation:
    def test_a_handover_meant_for_this_process_is_adopted(self, bind):
        srv, socket_mod, adopted, own = bind(
            listen_fds="1", listen_pid=str(os.getpid())
        )
        assert srv.reload_socket is True
        assert srv.socket is adopted
        socket_mod.socket.assert_called_once_with(fileno=3)
        assert not own.bind.called, "adopting a socket must not also bind one"

    def test_a_handover_meant_for_ANOTHER_process_is_ignored(self, bind):
        srv, socket_mod, _, own = bind(listen_fds="1", listen_pid=str(os.getpid() + 1))
        assert srv.reload_socket is False
        assert not socket_mod.socket.called, (
            "LISTEN_PID names the process the fds were passed to. Ignoring it "
            "means a child that inherited the variables adopts fd 3 — whatever "
            "fd 3 happens to be in that child"
        )
        assert own.bind.called, "it must bind its own socket instead"

    def test_more_than_one_passed_fd_is_not_handled(self, bind):
        srv, socket_mod, _, own = bind(listen_fds="2", listen_pid=str(os.getpid()))
        assert srv.reload_socket is False
        assert not socket_mod.socket.called
        assert own.bind.called

    def test_with_no_handover_at_all_it_binds_normally(self, bind):
        srv, socket_mod, _, own = bind()
        assert srv.reload_socket is False
        assert not socket_mod.socket.called
        assert own.bind.called

    def test_activate_skips_listen_on_an_adopted_socket(self, server):
        server.reload_socket = True
        server.socket = MagicMock()
        server.request_queue_size = 128
        server.server_activate()
        assert not server.socket.listen.called, (
            "the handed-over socket is already listening; calling listen() on "
            "it again resets its backlog"
        )

    def test_activate_listens_on_a_socket_it_bound_itself(self, server):
        server.reload_socket = False
        server.socket = MagicMock()
        server.request_queue_size = 128
        server.server_activate()
        server.socket.listen.assert_called_once_with(128)


class TestProcessRequestUnderThreadExhaustion:
    @pytest.fixture
    def dispatch(self, server):
        def _run(*, spawn_fails):
            served = []
            server.process_request_thread = MagicMock(
                side_effect=lambda *a: served.append(a)
            )
            made = []

            class _Thread:
                def __init__(self, target=None, args=()):
                    self.target, self.args = target, args
                    self.daemon = False
                    self.name = "t"
                    self.ident = 1
                    made.append(self)

                def start(self):
                    if spawn_fails:
                        raise RuntimeError("can't start new thread")

            with patch.object(wsgi.threading, "Thread", _Thread):
                server.process_request("req", ("127.0.0.1", 5555))
            return served, made

        return _run

    def test_normally_the_request_goes_to_a_thread(self, dispatch):
        served, made = dispatch(spawn_fails=False)
        assert served == [], "the thread body did not run, so nothing served here"
        assert made and made[0].args == ("req", ("127.0.0.1", 5555))
        assert made[0].daemon is True, (
            "a non-daemon request thread blocks interpreter shutdown"
        )

    def test_a_refused_thread_is_served_synchronously_not_dropped(self, dispatch):
        served, _ = dispatch(spawn_fails=True)
        assert served == [("req", ("127.0.0.1", 5555))], (
            "under thread exhaustion the choice is between serving slowly and "
            "dropping the connection with no response; dropping it looks like "
            "a network fault to the client"
        )

    def test_the_refusal_is_logged_with_the_thread_count(self, dispatch, caplog):
        dispatch(spawn_fails=True)
        assert "thread spawn failed" in caplog.text
        assert f"active={threading.active_count()}" in caplog.text or "active=" in (
            caplog.text
        ), "the count is the only clue about which limit was hit"


class TestAcceptFailureReleasesTheSlot:
    @pytest.fixture
    def accepting(self, server):
        def _run(*, error, max_threads=4):
            server.max_http_threads = max_threads
            server.http_threads_sem = threading.Semaphore(max_threads)
            server.http_threads_sem.acquire()
            with patch.object(
                wsgi.werkzeug.serving.BaseWSGIServer,
                "get_request",
                lambda self: (
                    (_ for _ in ()).throw(error) if error else ("sock", "addr")
                ),
            ):
                if error:
                    with pytest.raises(type(error)):
                        server.get_request()
                else:
                    assert server.get_request() == ("sock", "addr")
            return server.http_threads_sem

        return _run

    def test_a_failed_accept_returns_the_permit(self, accepting):
        sem = accepting(error=OSError(errno.ECONNABORTED, "aborted"))
        assert sem._value == 4, (
            f"the permit was not returned ({sem._value} of 4 free): every "
            f"aborted connection would shrink the pool by one, permanently, "
            f"until the worker is recycled"
        )

    def test_the_error_still_propagates(self, accepting):
        accepting(error=OSError(errno.EMFILE, "too many open files"))

    def test_a_successful_accept_keeps_the_permit_held(self, accepting):
        sem = accepting(error=None)
        assert sem._value == 3, (
            "the request is now being served; its slot belongs to it until "
            "shutdown_request gives it back"
        )

    def test_without_a_semaphore_there_is_nothing_to_release(self, server):
        server.max_http_threads = 0
        server.socket = MagicMock()
        server.socket.accept.side_effect = OSError(errno.EAGAIN, "again")
        with pytest.raises(OSError):
            server.get_request()
