import collections
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .core import request

if TYPE_CHECKING:
    import odoo.api


def newest_by_identity(classes: Iterable[type]) -> list[type]:
    # A module reloaded at runtime rebuilds its classes, so the same controller
    # arrives twice under one (module, qualname). The newest wins, at the
    # position the first one claimed. Registration (`__init_subclass__`) and
    # routing-map assembly (`routing._get_leaf_classes`) both need this rule;
    # it is spelled once, here, because two spellings of it drift.
    by_key: dict[tuple[str, str], int] = {}
    result: list[type] = []
    for cls in classes:
        key = (cls.__module__, cls.__qualname__)
        idx = by_key.get(key)
        if idx is None:
            by_key[key] = len(result)
            result.append(cls)
        else:
            result[idx] = cls
    return result


class Controller:
    children_classes: collections.defaultdict[str, list[type[Controller]]] = (
        collections.defaultdict(list)
    )

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if Controller in cls.__bases__:
            path = cls.__module__.split(".")
            module = path[2] if len(path) > 2 and path[:2] == ["odoo", "addons"] else ""
            bucket = Controller.children_classes[module]
            bucket[:] = newest_by_identity([*bucket, cls])

    @property
    def env(self) -> odoo.api.Environment | None:
        return request.env if request else None
