import collections
from typing import TYPE_CHECKING, Any

from .core import request

if TYPE_CHECKING:
    import odoo.api


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
            key = (cls.__module__, cls.__qualname__)
            for idx, existing in enumerate(bucket):
                if (existing.__module__, existing.__qualname__) == key:
                    bucket[idx] = cls
                    return
            bucket.append(cls)

    @property
    def env(self) -> odoo.api.Environment | None:
        return request.env if request else None
