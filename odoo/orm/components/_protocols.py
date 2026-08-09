"""The shapes ``components/`` requires of the objects it is handed.

The package must not import ``odoo.*`` at runtime
(``orm-components-are-pure-python``), so what it needs from a field is declared
structurally here rather than by importing ``Field``. That is also what lets the
unit tests pass a five-line ``NamedTuple`` instead of a real field.

**Each Protocol is as narrow as its consumer.** ``FieldCache`` reads exactly one
attribute off a field (``model_name``, to answer ``pop_dirty_for_model``) and
otherwise uses it as a dict key; requiring it to satisfy ``FieldLike`` would
oblige every cache test double to declare ``store``, ``relational``, ``compute``
and two more it never consults. The hierarchy is ordered by what is actually
read, so a double only implements what the code it exercises touches.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # TYPE_CHECKING only, so no runtime import of `odoo.*` occurs and the purity
    # contract is untouched -- `layer_check.py` skips these blocks for every
    # contract, and `components/tests/conftest.py`'s namespace stubs never see
    # them either. Verified 2026-08-09: `orm-components-are-pure-python: 0 new`
    # with this import present.
    #
    # `IdType` is imported rather than restated as `Hashable` because the weaker
    # spelling admits exactly the bug worth catching: a recordset is hashable,
    # so `cache.get_value(field, records)` would type-check against `Hashable`
    # and fail at runtime with a KeyError naming nothing.
    from ..primitives import IdType as RecordId
else:
    RecordId = object


class FieldKey(Protocol):
    """A field used purely as a cache/scheduling key -- no attribute is read.

    Deliberately the weakest of these: ``ComputeEngine`` never asks a field
    anything, it only stores ids against it, and ``recompute.py`` hands it a
    :class:`SchedulableField` while the unit tests hand it four-field
    NamedTuples. Requiring :class:`NamedField` there is what a first attempt at
    this did, and mypy reported it immediately -- 477 new errors, most of them
    call sites passing a perfectly good field the protocol did not describe. A
    protocol its own callers cannot satisfy is a worse lie than ``Any``.
    """

    def __hash__(self) -> int: ...


class NamedField(FieldKey, Protocol):
    """A field the cache can group by model, for ``pop_dirty_for_model``."""

    @property
    def model_name(self) -> str: ...


class SchedulableField(FieldKey, Protocol):
    @property
    def recursive(self) -> bool: ...

    @property
    def is_stored_computed(self) -> bool: ...


class FieldLike(NamedField, SchedulableField, Protocol):
    @property
    def type(self) -> str: ...

    @property
    def store(self) -> bool: ...

    @property
    def relational(self) -> bool: ...

    @property
    def compute(self) -> str | Callable[..., None] | None: ...
