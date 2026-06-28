"""Structural typing contracts for the fields the pure ORM engine reads.

The engine (``odoo.orm.components``) is deliberately decoupled from
:class:`odoo.fields.Field` and :class:`odoo.models.BaseModel` (ADR-0002): it
never imports them and receives field-like collaborators by injection. Those
collaborators were historically typed ``Any``, so the duck-typed contract lived
only in prose docstrings — a typo such as ``field.is_store_computed`` was
invisible to the type checker, and ``getattr(field, "store", False)`` could
silently mask a missing attribute as ``False``.

These ``Protocol`` classes make the contract explicit and *structural*: the real
``Field`` satisfies them without importing anything from this package, and the
engine's own code is checked against them. Defining them inside ``components``
preserves the package's purity contract (they import only the stdlib ``typing``
surface, never ``odoo.*``), so ``orm-components-are-pure-python`` still holds.

Two design choices keep them honest:

* **Read-only.** The engine only *reads* these attributes, so every member is a
  read-only ``property``. That states the real contract and, as a bonus, lets
  *immutable* field-likes (a ``NamedTuple`` test double, a frozen dataclass)
  satisfy them — fields are used as cache/recompute dict keys, so they must be
  hashable.
* **Segregated.** Each consumer depends on the *narrowest* protocol it needs:
  the recompute scheduler reads two attributes (:class:`SchedulableField`);
  richer consumers (cache, model graph) read more (:class:`FieldLike`). Extend a
  protocol only when the engine starts reading a new attribute — never
  speculatively.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class SchedulableField(Protocol):
    """The minimal field view the recompute scheduler reads.

    Just enough to route a trigger entry: whether the field is self-referential
    (cycle-prone) and whether it is stored-computed (recompute vs. invalidate).
    """

    @property
    def recursive(self) -> bool:
        """Whether the field depends on itself (cycle-prone trigger traversal)."""
        ...

    @property
    def is_stored_computed(self) -> bool:
        """Whether the field is both stored and computed."""
        ...


class FieldLike(SchedulableField, Protocol):
    """The full set of field attributes the pure ORM engine reads.

    A superset of :class:`SchedulableField`. The real
    :class:`odoo.fields.Field` satisfies this structurally; it types the
    ``field`` keys/params flowing through the cache and model-graph components.
    """

    @property
    def model_name(self) -> str:
        """``model.field``-qualifying model name (e.g. ``"res.partner"``)."""
        ...

    @property
    def type(self) -> str:
        """Field type discriminator (e.g. ``"many2one"``, ``"char"``)."""
        ...

    @property
    def store(self) -> bool:
        """Whether the field is persisted in the database."""
        ...

    @property
    def relational(self) -> bool:
        """Whether the field is relational (has a comodel)."""
        ...

    @property
    def compute(self) -> str | Callable[..., None] | None:
        """``None``, a method name, or a callable computing the field."""
        ...
