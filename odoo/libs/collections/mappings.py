"""Specialized mapping types and helpers."""

__all__ = ["ConstantMapping", "DotDict", "ReadonlyDict", "submap"]

from collections.abc import Iterable, Iterator, Mapping
from typing import Any


class ConstantMapping[T](Mapping[Any, T]):
    """An immutable mapping returning the provided value for every single key.

    Useful for default value to methods.

    Example::

        >>> m = ConstantMapping(42)
        >>> m['anything']
        42
        >>> m['something_else']
        42
    """

    __slots__ = ["_value"]

    def __init__(self, val: T) -> None:
        """Initialize the mapping with the value returned for every key."""
        self._value = val

    def __len__(self) -> int:
        """Return the number of keys, which is always zero."""
        return 0

    def __iter__(self) -> Iterator[Any]:
        """Return an iterator over the keys, which is always empty."""
        return iter(())

    def __getitem__(self, item: Any) -> T:
        """Return the constant value, regardless of ``item``."""
        return self._value


class ReadonlyDict[K, T](Mapping[K, T]):
    """Helper for an unmodifiable dictionary, not even updatable using `dict.update`.

    This is similar to a `frozendict`, with one drawback and one advantage:

    - `dict.update` works for a `frozendict` but not for a `ReadonlyDict`.
    - `json.dumps` works for a `frozendict` by default but not for a `ReadonlyDict`.

    This comes from the fact `frozendict` inherits from `dict`
    while `ReadonlyDict` inherits from `collections.abc.Mapping`.

    Example::

        >>> data = ReadonlyDict({'foo': 'bar'})
        >>> data['foo']
        'bar'
        >>> data['baz'] = 'xyz'
        Traceback (most recent call last):
        ...
        TypeError: 'ReadonlyDict' object does not support item assignment
    """

    __slots__ = ("_data__",)

    def __init__(self, data: Mapping[K, T]) -> None:
        """Initialize the read-only dictionary from another mapping."""
        self._data__ = dict(data)

    def __contains__(self, key: object) -> bool:
        """Return whether the dictionary contains ``key``."""
        return key in self._data__

    def __getitem__(self, key: K) -> T:
        """Return the value stored for ``key``."""
        return self._data__[key]

    def __len__(self) -> int:
        """Return the number of keys in the dictionary."""
        return len(self._data__)

    def __iter__(self) -> Iterator[K]:
        """Return an iterator over the keys."""
        return iter(self._data__)


def submap[K, T](mapping: Mapping[K, T], keys: Iterable[K]) -> Mapping[K, T]:
    """Get a filtered copy of the mapping where only some keys are present.

    :param mapping: The original dict-like structure to filter
    :param keys: The list of keys to keep
    :returns: A filtered dict copy of the original mapping

    Example::

        >>> submap({'a': 1, 'b': 2, 'c': 3}, ['a', 'c'])
        {'a': 1, 'c': 3}
        >>> submap({'x': 10, 'y': 20}, ['y', 'z'])
        {'y': 20}
    """
    keys = frozenset(keys)
    return {key: mapping[key] for key in mapping if key in keys}


class DotDict(dict):
    """Helper for dot.notation access to dictionary attributes.

    Example::

        >>> foo = DotDict({'bar': False, 'nested': {'value': 42}})
        >>> foo.bar
        False
        >>> foo.nested.value
        42
    """

    def __getattr__(self, attrib: str) -> Any:
        """Return the value for ``attrib``, wrapping nested dicts as ``DotDict``."""
        val = self.get(attrib)
        return DotDict(val) if isinstance(val, dict) else val
