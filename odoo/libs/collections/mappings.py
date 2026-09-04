__all__ = ["ConstantMapping", "DotDict", "ReadonlyDict", "submap"]

from collections.abc import Iterable, Iterator, Mapping
from typing import Any


class ConstantMapping[T](Mapping[Any, T]):
    __slots__ = ["_value"]

    def __init__(self, val: T) -> None:
        self._value = val

    def __len__(self) -> int:
        return 0

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __getitem__(self, item: Any) -> T:
        return self._value


class ReadonlyDict[K, T](Mapping[K, T]):
    """Guarantees the mapping itself cannot be mutated through this wrapper.
    The guarantee is shallow only: ``__init__`` copies one level (``dict(data)``),
    so a nested mutable value (a list, a dict) inside a "readonly" mapping
    remains fully mutable through its own reference.
    """

    __slots__ = ("_data__",)

    def __init__(self, data: Mapping[K, T]) -> None:
        self._data__ = dict(data)

    def __contains__(self, key: object) -> bool:
        return key in self._data__

    def __getitem__(self, key: K) -> T:
        return self._data__[key]

    def __len__(self) -> int:
        return len(self._data__)

    def __iter__(self) -> Iterator[K]:
        return iter(self._data__)


def submap[K, T](mapping: Mapping[K, T], keys: Iterable[K]) -> Mapping[K, T]:
    keys = frozenset(keys)
    return {key: mapping[key] for key in mapping if key in keys}


class DotDict(dict):
    """Dict with attribute access. A missing key returns ``None``, not
    ``AttributeError`` -- deliberate (see test_mappings.py), so every real
    instantiation of this class in the tree is test-support code, never
    production data.
    """

    def __getattr__(self, attrib: str) -> Any:
        val = self.get(attrib)
        return DotDict(val) if isinstance(val, dict) else val
