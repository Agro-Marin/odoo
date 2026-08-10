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
    def __hash__(self) -> int: ...


class NamedField(FieldKey, Protocol):
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
