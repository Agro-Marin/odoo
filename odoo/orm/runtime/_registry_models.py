import functools
import typing
from collections import deque
from collections.abc import Iterable, Iterator
from operator import attrgetter

from odoo.tools import OrderedSet

from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.models import BaseModel


class _RegistryModelsMixin(_RegistryStubs):
    __slots__ = ()

    models: dict[str, type[BaseModel]]

    def _init_models_container(self) -> None:
        self.models = {}

    def __len__(self) -> int:
        return len(self.models)

    def __iter__(self) -> Iterator[str]:
        return iter(self.models)

    def __getitem__(self, model_name: str) -> type[BaseModel]:
        return self.models[model_name]

    def __setitem__(self, model_name: str, model: type[BaseModel]) -> None:
        self.models[model_name] = model

    def __delitem__(self, model_name: str) -> None:
        del self.models[model_name]
        for Model in self.models.values():
            Model._inherit_children.discard(model_name)

    @functools.cached_property
    def models_by_table(self) -> dict[str, type[BaseModel]]:
        by_table: dict[str, type[BaseModel]] = {}
        for model_cls in self.models.values():
            if table := getattr(model_cls, "_table", None):
                by_table.setdefault(table, model_cls)
        return by_table

    def descendants(
        self,
        model_names: Iterable[str],
        *kinds: typing.Literal["_inherit", "_inherits"],
    ) -> OrderedSet[str]:
        if not all(kind in ("_inherit", "_inherits") for kind in kinds):
            raise ValueError(
                f"descendants: kinds must be '_inherit'/'_inherits', got {kinds!r}"
            )
        funcs = [attrgetter(kind + "_children") for kind in kinds]

        models: OrderedSet[str] = OrderedSet()
        queue = deque(model_names)
        while queue:
            model = self.models.get(queue.popleft())
            if model is None or model._name in models:
                continue
            models.add(model._name)
            for func in funcs:
                queue.extend(func(model))
        return models
