from __future__ import annotations

from typing import Any, Protocol


class SqlReader(Protocol):
    """What a function needs from a cursor to run a query and read it back.

    Narrower than :class:`odoo.db.cursor.Cursor` on purpose, and for the reason
    :class:`odoo.db.savepoint.SavepointHost` is: annotating the full concrete
    cursor claims a dependency the function does not have, and the claim is not
    free -- every caller that legitimately has something else, a test double
    most of all, is then either a lie to the type checker or a reason to widen
    the double until it is no longer a double.

    Two members, because two is what these functions use.
    """

    def execute(self, query: Any, /, *args: Any, **kwargs: Any) -> Any: ...

    def fetchall(self) -> list[Any]: ...
