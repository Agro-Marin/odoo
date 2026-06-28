"""Immutable dictionary type and a hashing helper for arbitrary objects."""

__all__ = ["freehash", "frozendict"]

from collections.abc import Iterable, Mapping
from typing import Any


def freehash(arg: Any) -> int:
    """Compute a hash for any object, including unhashable ones.

    For unhashable objects (dicts, lists, etc.), attempts to convert
    them to a hashable form (frozendict, frozenset).
    """
    try:
        return hash(arg)
    except Exception:
        if isinstance(arg, Mapping):
            return hash(frozendict(arg))
        elif isinstance(arg, Iterable):
            return hash(frozenset(freehash(item) for item in arg))
        else:
            return id(arg)


class frozendict[K, T](dict[K, T]):
    """An implementation of an immutable dictionary."""

    __slots__ = ("_hash",)

    def __delitem__(self, key: K) -> None:
        """Reject item deletion, as the dictionary is immutable."""
        msg = "'__delitem__' not supported on frozendict"
        raise NotImplementedError(msg)

    def __setitem__(self, key: K, val: T) -> None:
        """Reject item assignment, as the dictionary is immutable."""
        msg = "'__setitem__' not supported on frozendict"
        raise NotImplementedError(msg)

    def clear(self) -> None:
        """Reject clearing, as the dictionary is immutable."""
        msg = "'clear' not supported on frozendict"
        raise NotImplementedError(msg)

    def pop(self, key: K, default: T | None = None) -> T:
        """Reject popping a key, as the dictionary is immutable."""
        msg = "'pop' not supported on frozendict"
        raise NotImplementedError(msg)

    def popitem(self) -> tuple[K, T]:
        """Reject popping an item, as the dictionary is immutable."""
        msg = "'popitem' not supported on frozendict"
        raise NotImplementedError(msg)

    def setdefault(self, key: K, default: T | None = None) -> T:
        """Reject setting a default, as the dictionary is immutable."""
        msg = "'setdefault' not supported on frozendict"
        raise NotImplementedError(msg)

    def update(self, *args: Any, **kwargs: Any) -> None:
        """Reject updating, as the dictionary is immutable."""
        msg = "'update' not supported on frozendict"
        raise NotImplementedError(msg)

    def __hash__(self) -> int:  # type: ignore[override]
        """Return a cached hash computed from the key/value pairs."""
        try:
            return self._hash  # type: ignore[has-type]
        except AttributeError:
            h = hash(frozenset((key, freehash(val)) for key, val in self.items()))
            object.__setattr__(self, "_hash", h)
            return h
