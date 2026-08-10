from collections import defaultdict
from typing import TYPE_CHECKING, Any

from ._protocols import FieldKey

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


class _StackMap[F: FieldKey = FieldKey]:
    __slots__ = ("_maps",)

    def __init__(self) -> None:
        self._maps: list[dict[F, frozenset[Any]]] = []

    def get(
        self, key: F, default: frozenset[Any] | None = None
    ) -> frozenset[Any] | None:
        maps = self._maps
        i = len(maps)
        while i:
            i -= 1
            m = maps[i]
            if key in m:
                return m[key]
        return default

    def pushmap(self, m: dict[F, frozenset[Any]] | None = None) -> None:
        self._maps.append(m if m is not None else {})

    def popmap(self) -> dict[F, frozenset[Any]]:
        return self._maps.pop()

    def __setitem__(self, key: F, value: frozenset[Any]) -> None:
        self._maps[-1][key] = value

    def __len__(self) -> int:
        return len(self._maps)


class ComputeEngine[F: FieldKey = FieldKey]:
    __slots__ = ("_pending", "_protected")

    def __init__(self, pending_factory: type | None = None) -> None:
        self._pending: defaultdict[F, set[Any]] = defaultdict(pending_factory or set)
        self._protected: _StackMap[F] = _StackMap()

    @property
    def pending(self) -> defaultdict[F, set[Any]]:
        return self._pending

    def schedule(self, field: F, ids: Iterable[Any]) -> None:
        existing = self._pending.get(field)
        if existing is None:
            ids = list(ids)
            if not ids:
                return
            existing = self._pending[field]
        existing.update(ids)

    def mark_done(self, field: F, ids: Iterable[Any]) -> None:
        pending = self._pending.get(field)
        if pending is None:
            return
        pending.difference_update(ids)
        if not pending:
            del self._pending[field]

    def is_pending(self, field: F, record_id: Any) -> bool:
        return record_id in self._pending.get(field, ())

    def pending_ids(self, field: F) -> set[Any] | tuple[()]:
        return self._pending.get(field, ())

    def pending_fields(self) -> Collection[F]:
        return self._pending.keys()

    def has_pending(self) -> bool:
        return bool(self._pending)

    def has_pending_field(self, field: F) -> bool:
        return field in self._pending

    def pending_real_fields(self) -> list[F]:
        return [field for field, ids in self._pending.items() if any(ids)]

    def discard_field(self, field: F) -> None:
        self._pending.pop(field, None)

    def is_protected(self, field: F, record_id: Any) -> bool:
        return record_id in (self._protected.get(field) or ())

    def protected_ids(self, field: F) -> frozenset[Any]:
        return self._protected.get(field) or frozenset()

    def push_protection(self) -> None:
        self._protected.pushmap()

    def pop_protection(self) -> dict[F, frozenset[Any]]:
        return self._protected.popmap()

    def protect(self, field: F, ids: frozenset[Any]) -> None:
        existing = self._protected.get(field)
        self._protected[field] = existing.union(ids) if existing else ids

    def clear(self) -> None:
        self._pending.clear()

    def __repr__(self) -> str:
        n_fields = len(self._pending)
        n_entries = sum(len(ids) for ids in self._pending.values())
        n_scopes = len(self._protected)
        return f"<ComputeEngine pending={n_fields}f/{n_entries}e scopes={n_scopes}>"
