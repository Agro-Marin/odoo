from __future__ import annotations

import typing
from collections import deque
from dataclasses import dataclass, field

from odoo.tools import OrderedSet

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.models import BaseModel


@dataclass(slots=True)
class InitModelsPhase:
    install: bool

    #: Callables deferred until every model's table exists. A field cannot add
    #: its foreign key while the comodel's table may still be missing, so it
    #: queues the work here and ``init_models`` drains the queue after the
    #: reflection pass.
    post_init_queue: deque[Callable[[], None]] = field(default_factory=deque)

    #: ``{(table, column): (ref_table, ref_column, ondelete, model, module)}``
    #: -- the foreign keys this run wants, reconciled against the catalogue in
    #: one batch by ``check_foreign_keys``.
    foreign_keys: dict[tuple[str, str], tuple[str, str, str, BaseModel, str]] = field(
        default_factory=dict
    )

    #: ``(model_name, relation_table, module)`` for every many2many relation
    #: seen, handed to ``ir.model.relation._reflect_relations``, which keys on
    #: ``(table, module)`` and keeps the first model that declared it.
    relation_reflections: OrderedSet[tuple[str, str, str]] = field(
        default_factory=OrderedSet
    )
