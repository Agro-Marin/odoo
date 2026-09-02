import typing
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet

from odoo.tools import OrderedSet

from ...primitives import Command

if typing.TYPE_CHECKING:
    from ...primitives import IdType, ValuesType


# A CLEAR or SET supersedes every CREATE, LINK and UNLINK before it -- the
# field's content is what the last replacement said plus the commands after it
# -- while UPDATE and DELETE act on existing records and survive one. A dict in
# the list is a CREATE; any other non-command entry is the id of a record to LINK.
# On a record being created there is nothing to replace, so `superseding=False`
# keeps everything and a SET is only the ids to link.
class CommandDelta:
    __slots__ = (
        "created",
        "deleted",
        "linked",
        "replaced",
        "set_ids",
        "superseding",
        "unlinked",
        "updated",
    )

    def __init__(self) -> None:
        self.created: list[tuple[typing.Any, ValuesType]] = []
        self.updated: list[tuple[IdType, ValuesType]] = []
        self.deleted: OrderedSet[IdType] = OrderedSet()
        self.linked: OrderedSet[IdType] = OrderedSet()
        self.unlinked: OrderedSet[IdType] = OrderedSet()
        self.replaced: bool = False
        self.set_ids: tuple[IdType, ...] = ()
        self.superseding: bool = True

    @classmethod
    def fold(
        cls,
        commands: Iterable[typing.Any] | None,
        normalize: Callable[[typing.Any], IdType] = lambda id_: id_,
        *,
        superseding: bool = True,
    ) -> typing.Self:
        delta = cls()
        delta.superseding = superseding
        for command in commands or ():
            if isinstance(command, dict):
                delta.created.append((None, command))
                continue
            if not isinstance(command, (tuple, list)):
                delta._link(normalize(command))
                continue
            if not command:
                continue
            match command[0]:
                case Command.CREATE:
                    delta.created.append((command[1], command[2]))
                case Command.UPDATE:
                    delta.updated.append((normalize(command[1]), command[2]))
                case Command.DELETE:
                    id_ = normalize(command[1])
                    delta.deleted.add(id_)
                    delta.linked.discard(id_)
                case Command.UNLINK:
                    id_ = normalize(command[1])
                    delta.unlinked.add(id_)
                    delta.linked.discard(id_)
                case Command.LINK:
                    delta._link(normalize(command[1]))
                case Command.CLEAR:
                    delta._replace(())
                case Command.SET:
                    ids = command[2]
                    if ids.__class__ is int:
                        ids = (ids,)
                    delta._replace(tuple(normalize(id_) for id_ in ids))
        return delta

    def _link(self, id_: IdType) -> None:
        self.linked.add(id_)
        self.unlinked.discard(id_)

    def _replace(self, ids: tuple[IdType, ...]) -> None:
        self.replaced = True
        self.set_ids = ids
        if self.superseding:
            self.created.clear()
            self.linked.clear()
            self.unlinked.clear()

    @property
    def removed(self) -> AbstractSet[IdType]:
        return self.unlinked | self.deleted

    def final_ids(
        self, current: Iterable[IdType], created_ids: Iterable[IdType] = ()
    ) -> OrderedSet[IdType]:
        ids = OrderedSet(self.set_ids if self.replaced else current)
        ids -= self.removed
        ids.update(self.linked)
        ids.update(created_ids)
        return ids
