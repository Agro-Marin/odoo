from __future__ import annotations

from typing import Any, Protocol


class SqlReader(Protocol):
    def execute(self, query: Any, /, *args: Any, **kwargs: Any) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class GraphSqlReader(SqlReader, Protocol):
    @property
    def rowcount(self) -> int: ...
