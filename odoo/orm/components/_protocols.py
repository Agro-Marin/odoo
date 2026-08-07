from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class SchedulableField(Protocol):
    @property
    def recursive(self) -> bool: ...

    @property
    def is_stored_computed(self) -> bool: ...


class FieldLike(SchedulableField, Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def type(self) -> str: ...

    @property
    def store(self) -> bool: ...

    @property
    def relational(self) -> bool: ...

    @property
    def compute(self) -> str | Callable[..., None] | None: ...
