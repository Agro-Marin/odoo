from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Protocol

__all__ = ["OptionSource", "SettingsSlot"]


class OptionSource(Protocol):
    def __getitem__(self, key: str, /) -> Any: ...


class SettingsSlot[T]:
    """A process-global settings holder with a swappable install/override.

    ``installed``/``override`` mutate ``_installed`` via a plain try/finally,
    with no lock or contextvar: nested/sequential use on one thread restores
    correctly, but two threads calling ``override`` concurrently on the same
    slot would race (one thread's restore in ``finally`` can clobber the
    other's still-active override). This is a single-threaded/test-only
    contract today -- every real production call site uses the one-shot
    ``provide`` setter instead; every ``installed``/``override`` caller found
    is test code, sequential or nested, never concurrent. Back ``_installed``
    with a ``contextvars.ContextVar`` first if concurrent use is ever needed.

    ``is_installed``/``current`` use ``self._installed is not None`` as the
    "was something installed" test, so a settings object where ``None`` is
    itself a legitimate value would be indistinguishable from "nothing
    installed" -- not exercised today, since every real settings type here
    (``PoolSettings``/``HttpSettings``/``ServerSettings``) is a plain
    dataclass instance, never ``None``.
    """

    __slots__ = ("_installed", "_name", "_source")

    def __init__(self, name: str, source: Callable[[], T] | None = None) -> None:
        self._name = name
        self._source = source
        self._installed: T | None = None

    def provide(self, source: Callable[[], T]) -> None:
        self._source = source

    @property
    def is_installed(self) -> bool:
        return self._installed is not None

    def current(self) -> T:
        if self._installed is not None:
            return self._installed
        if self._source is None:
            raise RuntimeError(
                f"{self._name} has no settings source and nothing installed; "
                f"the process bootstrap provides one before the first read"
            )
        return self._source()

    @contextmanager
    def installed(self, settings: T) -> Iterator[T]:
        previous = self._installed
        self._installed = settings
        try:
            yield settings
        finally:
            self._installed = previous

    @contextmanager
    def override(self, **changes: Any) -> Iterator[T]:
        with self.installed(replace(self.current(), **changes)) as settings:  # type: ignore[type-var]
            yield settings
