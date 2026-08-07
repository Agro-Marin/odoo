"""A prefork worker must close the accepted socket even when the handler raises.

``socketserver.BaseServer.process_request`` is ``finish_request(...)`` followed
by ``shutdown_request(...)`` with **no** ``try/finally``, so any exception out of
the handler skips the close and leaks the accepted socket for the remainder of
the worker's life.  ``WorkerHTTP.process_request`` suppressed ``BrokenPipeError``
around that call — i.e. it treated as routine precisely the exception that
leaks — so a client that hangs up mid-response leaked an fd each time.  Enough of
them and ``accept()`` starts raising ``EMFILE``, which ``process_work`` re-raises,
which kills the worker; the master then respawns it into the same condition.

These tests drive ``WorkerHTTP.process_request`` against a stub server, so they
need no listening socket, no fork and no database.
"""

import contextlib
import socket
from unittest.mock import MagicMock

import pytest

from odoo.service._worker import WorkerHTTP


class _StubServer:
    """The two socketserver hooks WorkerHTTP.process_request uses."""

    def __init__(self, raise_on_finish=None):
        self._raise_on_finish = raise_on_finish
        self.socket = None
        self.shutdown_calls = []

    def finish_request(self, request, client_address):
        if self._raise_on_finish is not None:
            raise self._raise_on_finish

    def shutdown_request(self, request):
        self.shutdown_calls.append(request)
        request.close()


@pytest.fixture
def worker():
    """A WorkerHTTP with just enough state for process_request."""
    w = WorkerHTTP.__new__(WorkerHTTP)
    w.sock_timeout = 5
    w.request_count = 0
    return w


def _socketpair():
    """A connected AF_INET pair.

    Not ``socket.socketpair()``: that is AF_UNIX, and ``process_request`` sets
    ``TCP_NODELAY``, which AF_UNIX rejects with ``OSError(ENOTSUP)``.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        accepted, _ = listener.accept()
    finally:
        listener.close()
    return accepted, client


@pytest.mark.parametrize(
    "failure",
    [None, BrokenPipeError("client hung up"), ValueError("handler blew up")],
    ids=["clean", "broken-pipe", "unexpected-error"],
)
def test_accepted_socket_is_always_closed(worker, failure):
    client, peer = _socketpair()
    try:
        worker.server = _StubServer(raise_on_finish=failure)
        # An unexpected error must still propagate (pinned separately below);
        # what this test asserts is that it is cleaned up on the way out.
        with contextlib.suppress(ValueError):
            worker.process_request(client, ("127.0.0.1", 1234))
        assert worker.server.shutdown_calls == [client], "socket was not released"
        assert client.fileno() == -1, "socket left open -- this is the fd leak"
    finally:
        peer.close()
        if client.fileno() != -1:
            client.close()


def test_broken_pipe_is_still_swallowed(worker):
    """Unchanged behaviour: a client hanging up is routine, not a worker error."""
    client, peer = _socketpair()
    try:
        worker.server = _StubServer(raise_on_finish=BrokenPipeError())
        worker.process_request(client, ("127.0.0.1", 1234))  # must not raise
        assert worker.request_count == 1
    finally:
        peer.close()


def test_unexpected_errors_still_propagate(worker):
    """Cleanup must not turn a real bug into a silent one."""
    client, peer = _socketpair()
    try:
        worker.server = _StubServer(raise_on_finish=ValueError("boom"))
        with pytest.raises(ValueError, match="boom"):
            worker.process_request(client, ("127.0.0.1", 1234))
    finally:
        peer.close()


def test_request_count_advances_only_on_a_completed_request(worker):
    """`request_count` drives limit_request recycling."""
    client, peer = _socketpair()
    try:
        worker.server = _StubServer()
        worker.process_request(client, ("127.0.0.1", 1234))
        assert worker.request_count == 1
    finally:
        peer.close()


def test_socket_options_are_applied_before_handling(worker):
    """The pre-handler setup must survive the try/finally restructure."""
    client, peer = _socketpair()
    try:
        worker.server = _StubServer()
        client_spy = MagicMock(wraps=client)
        client_spy.fileno.return_value = client.fileno()
        worker.process_request(client_spy, ("127.0.0.1", 1234))
        client_spy.settimeout.assert_called_once_with(worker.sock_timeout)
        client_spy.setsockopt.assert_called_once_with(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
        )
    finally:
        peer.close()
        client.close()
