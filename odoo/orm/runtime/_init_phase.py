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

    post_init_queue: deque[Callable[[], None]] = field(default_factory=deque)

    foreign_keys: dict[tuple[str, str], tuple[str, str, str, BaseModel, str]] = field(
        default_factory=dict
    )

    relation_reflections: OrderedSet[tuple[str, str, str]] = field(
        default_factory=OrderedSet
    )
