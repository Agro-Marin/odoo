"""The process's server, and whether it is on its way to a re-exec.

Two mutable module globals, in a module that imports nothing from this package.
They lived in `lifecycle` next to `start()`, which is what made the dependency
graph two-way: `lifecycle` needs the server classes to build one, and the server
classes need this state to reach it.  Four modules paid for that with a deferred
import.  Nothing imports `lifecycle` for these any more.

`server` is a singleton by construction -- one process serves one way -- and
`server_phoenix` is the flag a SIGHUP raises so the shutdown path knows to hand
the socket to a successor instead of closing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._base_server import CommonServer

server: CommonServer | None = None

server_phoenix = False


def set_server(value: CommonServer | None) -> None:
    global server  # noqa: PLW0603  the running server IS a process singleton

    server = value


def set_phoenix(value: bool) -> None:
    global server_phoenix  # noqa: PLW0603  one re-exec decision per process

    server_phoenix = value
