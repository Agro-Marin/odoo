import enum
import typing
from collections.abc import Collection, Mapping
from collections.abc import Set as AbstractSet
from typing import Self

from odoo.tools import SQL

type ContextType = Mapping[str, typing.Any]
type ValuesType = dict[str, typing.Any]

COLLECTION_TYPES = (list, tuple, AbstractSet)


class NewId:
    __slots__ = ("__hash", "origin", "ref")

    def __init__(self, origin: int | None = None, ref: typing.Any = None) -> None:
        self.origin = origin
        self.ref = ref
        if origin is not None:
            self.__hash = hash(origin)
        elif ref is not None:
            self.__hash = hash(ref)
        else:
            self.__hash = id(self)

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, NewId):
            return NotImplemented
        if self.origin is not None and other.origin is not None:
            return self.origin == other.origin
        if self.origin is None and other.origin is None:
            if self.ref is not None and other.ref is not None:
                return self.ref == other.ref
        return False

    def __hash__(self) -> int:
        return self.__hash

    def __lt__(self, other: object) -> bool:
        if isinstance(other, NewId):
            s, o = self.origin, other.origin
            if s is None:
                return False
            if o is None:
                return True
            return s < o
        if isinstance(other, int):
            if self.origin is None:
                return False
            return self.origin < other
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if self is other:
            return True
        if isinstance(other, NewId):
            if self == other:
                return True
            s, o = self.origin, other.origin
            if s is None:
                return False
            if o is None:
                return True
            return s <= o
        if isinstance(other, int):
            if self.origin is None:
                return False
            return self.origin < other
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, NewId):
            s, o = self.origin, other.origin
            if s is None and o is None:
                return False
            if s is None:
                return True
            if o is None:
                return False
            return s > o
        if isinstance(other, int):
            if self.origin is None:
                return True
            return self.origin >= other
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if self is other:
            return True
        if isinstance(other, NewId):
            if self == other:
                return True
            s, o = self.origin, other.origin
            if s is None and o is None:
                return False
            if s is None:
                return True
            if o is None:
                return False
            return s >= o
        if isinstance(other, int):
            if self.origin is None:
                return True
            return self.origin >= other
        return NotImplemented

    def __repr__(self) -> str:
        if self.origin is not None:
            return f"<NewId origin={self.origin!r}>"
        if self.ref is not None:
            return f"<NewId ref={self.ref!r}>"
        return f"<NewId 0x{id(self):x}>"

    def __str__(self) -> str:
        if self.origin is not None:
            id_part = repr(self.origin)
        elif self.ref is not None:
            id_part = repr(self.ref)
        else:
            id_part = hex(id(self))
        return f"NewId_{id_part}"


type IdType = int | NewId | str


class Command(enum.IntEnum):
    CREATE = 0
    UPDATE = 1
    DELETE = 2
    UNLINK = 3
    LINK = 4
    CLEAR = 5
    SET = 6

    @classmethod
    def create(cls, values: ValuesType) -> CommandValue:
        return (cls.CREATE, 0, values)

    @classmethod
    def update(cls, id: int, values: ValuesType) -> CommandValue:
        return (cls.UPDATE, id, values)

    @classmethod
    def delete(cls, id: int) -> CommandValue:
        return (cls.DELETE, id, 0)

    @classmethod
    def unlink(cls, id: int) -> CommandValue:
        return (cls.UNLINK, id, 0)

    @classmethod
    def link(cls, id: int) -> CommandValue:
        return (cls.LINK, id, 0)

    @classmethod
    def clear(cls) -> CommandValue:
        return (cls.CLEAR, 0, 0)

    @classmethod
    def set(cls, ids: Collection[int]) -> CommandValue:
        return (cls.SET, 0, ids)


type CommandValue = tuple[
    Command, int, typing.Literal[0] | ValuesType | Collection[int]
]


SUPERUSER_ID = 1

SQL_DEFAULT = SQL("DEFAULT")

SQL_OPERATORS = {
    "=": SQL(" = "),
    "!=": SQL(" != "),
    "in": SQL(" IN "),
    "not in": SQL(" NOT IN "),
    "<": SQL(" < "),
    ">": SQL(" > "),
    "<=": SQL(" <= "),
    ">=": SQL(" >= "),
    "like": SQL(" LIKE "),
    "ilike": SQL(" ILIKE "),
    "=like": SQL(" LIKE "),
    "=ilike": SQL(" ILIKE "),
    "not like": SQL(" NOT LIKE "),
    "not ilike": SQL(" NOT ILIKE "),
    "not =like": SQL(" NOT LIKE "),
    "not =ilike": SQL(" NOT ILIKE "),
}


LOG_ACCESS_COLUMNS = ["create_uid", "create_date", "write_uid", "write_date"]

MAGIC_COLUMNS = ["id"] + LOG_ACCESS_COLUMNS


STATE_FIELD = "state"
"""A field named ``state`` defaults to ``copy=False`` (``Field._get_attrs``)."""

SEQUENCE_FIELD = "sequence"
"""A field named ``sequence`` defaults to ``aggregator=None`` (``Integer._get_attrs``)."""

CONVENTIONAL_FIELD_NAMES: dict[str, str] = {
    STATE_FIELD: "defaults to copy=False -- a workflow state is not duplicated",
    SEQUENCE_FIELD: "defaults to aggregator=None -- ordering numbers are not summed",
    "currency_id": "Monetary's implicit currency field (then x_currency_id)",
    "company_id": "the implicit _check_company target on a relational field",
    "display_name": "the computed label, special-cased in search and expressions",
}
"""Field names the ORM attaches behaviour to, purely because of the name.

Collected here because they were five inline string literals spread across four
Layer-1 modules -- ``fields/base.py``, ``fields/numeric.py``,
``fields/relational/_base.py`` and ``fields/textual.py`` -- with nothing telling
a reader that naming a field ``sequence`` changes its aggregator, or that naming
one ``state`` stops it being copied.

The last three are documented framework features. The first two are **business
convention compiled into the framework**: the ORM knows what an Odoo workflow
field is called. That is the same shape as the addon-owned cache bucket in
``orm/runtime/registry.py`` -- addon vocabulary the ``core-does-not-depend-on-addons``
gate cannot see, because it is spelled as a string. Keeping the set in one Layer-0
table makes it greppable and countable; it does not make it smaller.

This mapping is documentation. The two names the ORM branches on are also exported
as constants above, and those are what the branches use.
"""

NO_ACCESS = "."

MODULE_UNINSTALL_FLAG = "_force_unlink"
"""Context key that suppresses ``@api.ondelete`` guards during uninstallation.

``UnlinkMixin.unlink`` reads it to decide whether a model's ``@api.ondelete``
methods run, so it governs *ORM* behaviour and belongs to the ORM. It lived in
``odoo.addons.base.models.ir_model_common`` until 19.0-marin, which inverted the
dependency: the framework had to reach into an addon to learn the name of a flag
its own delete path branches on. ``addons/base`` re-exports it for the
``ir_model*`` / ``ir_module`` consumers that set it.
"""


INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100


__all__ = [
    "COLLECTION_TYPES",
    "CONVENTIONAL_FIELD_NAMES",
    "INSERT_BATCH_SIZE",
    "LOG_ACCESS_COLUMNS",
    "MAGIC_COLUMNS",
    "MODULE_UNINSTALL_FLAG",
    "NO_ACCESS",
    "SEQUENCE_FIELD",
    "SQL_DEFAULT",
    "SQL_OPERATORS",
    "STATE_FIELD",
    "SUPERUSER_ID",
    "UPDATE_BATCH_SIZE",
    "Command",
    "CommandValue",
    "ContextType",
    "IdType",
    "NewId",
    "Self",
    "ValuesType",
]
