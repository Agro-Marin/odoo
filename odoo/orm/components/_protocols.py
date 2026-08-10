from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
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
