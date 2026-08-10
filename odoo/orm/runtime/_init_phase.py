"""State that exists only while :meth:`Registry.init_models` is running.

Until 2026-08-09 these four lived as attributes created inside ``init_models``'
``try:`` and ``del``-eted in its ``finally:``::

    try:
        self._post_init_queue = deque()
        self._foreign_keys = {}
        self._relation_reflections = OrderedSet()
        self._is_install = install
        ...
    finally:
        del self._post_init_queue
        del self._foreign_keys
        del self._relation_reflections
        del self._is_install

``doc/architecture/module.md`` documents one of them, ``_relation_reflections``,
as "the sharpest temporal coupling in the ORM and the one least visible to every
structural gate". There were four, reached from six sites outside
``registry.py`` -- five of them in **Layer 1** (``fields/base.py``,
``fields/relational/many2one.py``, ``fields/relational/many2many.py``) plus the
schema mixin -- and four more ``post_init`` calls from ``addons/base``.

Nothing declared the ordering and nothing but an ``AttributeError`` enforced it.
The strongest evidence that this was a defect rather than a style was
``_registry_stubs.py``: a class whose entire body is ``if TYPE_CHECKING:``
declarations, inherited solely so mypy could see attributes with no honest
definition site, listing ``_foreign_keys`` and ``_is_install`` beside genuinely
permanent members and thereby erasing the one distinction that matters -- which
of these exist right now.

One nullable attribute replaces the four. It can be declared, its absence names
itself, and "am I inside the phase?" becomes a question with an answer.
"""

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
    """The open window of one ``init_models()`` call.

    :param install: whether the modules being initialised are being *installed*
        rather than updated. Read by ``post_constraint`` to decide whether a
        failing constraint is an error or an expected retry.
    """

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
