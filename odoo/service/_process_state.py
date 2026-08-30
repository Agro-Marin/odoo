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
