"""The registry's model container — its ``Mapping`` half, as a leaf.

``Registry`` is the ORM's **third** ``__slots__``-mixin composition, built the
same way as ``BaseModel``/``_ModelStubs`` and ``Field``/``_FieldStubs``: a root
class over ``*Mixin`` bases with a typing-only stub declaring the shared
surface.  It was measured by neither gate until this module existed, and the
first measurement found what the absence of a gate had allowed --- a **3-unit
cycle over 4 edges**, the only one of the three compositions that was not a
DAG:

    registry.py      -> _registry_fields   (_ensure_field_triggers, field_depends,
                                            field_depends_context)
    registry.py      -> _registry_schema   (check_foreign_keys, check_indexes,
                                            check_tables_exist)
    _registry_fields -> registry.py        (models)
    _registry_schema -> registry.py        (models, init_phase)

``scc_without_base`` was 1, which says precisely where it came from: every
back-edge landed on the composition **root**.  That is the shape ``BaseModel``
had before the 2026-08a metadata split and ``Field`` had before
``_FieldMetadataMixin``, and it is broken the same way --- by moving the cluster
the mixins reach for off the root onto a leaf that reaches nothing back.

This module is that leaf for the **model container**: the ``models`` dict and
the ``Mapping`` protocol over it.  Its out-degree into the composition is zero
--- every member here reads only ``self.models``, which it owns --- so nothing
it is given can close a cycle --- the design rule stated under *Coupling
the import graph cannot see* in ``doc/architecture/module.md``.

The cluster is deliberately the *container* rather than all of ``Registry``'s
~33 attributes: it is what ``_registry_fields`` and ``_registry_schema``
actually ask the root for, and --- with ``init_phase``, the other leaf --- the
only one whose removal moves the graph.  Widening it would be a larger move
with no gate movement to show for it.
"""

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
    """``{model_name: model_cls}`` for one database, and the reads over it.

    Both the declaration and the initialisation live here. An earlier version
    left ``self.models = {}`` in ``Registry.init`` on the reasoning that "the
    root reaching a leaf is a legal DAG edge and moving the assignment would buy
    no graph movement" — true of the graph, and the wrong test. Under
    assignment-site ownership the root still owned the container, which is
    exactly the ambiguity :func:`unowned_shared_state` was added to count.
    """

    __slots__ = ()

    models: dict[str, type[BaseModel]]

    def _init_models_container(self) -> None:
        """Initialise this mixin's own state. Called by ``Registry.init``."""
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
        """``{table_name: model_cls}`` — the first model declaring each table.

        "First" reproduces the linear scan this replaces: several models can
        share a table (``_inherits`` delegation, an explicit ``_table``), and
        the previous readers took the first match in registry order, so
        ``setdefault`` over ``self.models.values()`` is the same answer without
        the scan.

        Invalidated with the other cached properties by
        ``reset_cached_properties(self)`` in ``Registry.load`` and
        ``Registry._setup_models__``, which are the only places ``models``
        changes.
        """
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
            # ``self.models.get`` rather than ``Mapping.get``: identical answer
            # (``__getitem__`` is a bare ``self.models`` read) without making
            # this leaf depend on the ``Mapping`` half of the root's bases.
            model = self.models.get(queue.popleft())
            if model is None or model._name in models:
                continue
            models.add(model._name)
            for func in funcs:
                queue.extend(func(model))
        return models
