from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


class _StackMap:
    __slots__ = ("_maps",)

    def __init__(self) -> None:
        self._maps: list[dict[Any, Any]] = []

    def get(self, key: Any, default: Any = None) -> Any:
        maps = self._maps
        i = len(maps)
        while i:
            i -= 1
            m = maps[i]
            if key in m:
                return m[key]
        return default

    def pushmap(self, m: dict[Any, Any] | None = None) -> None:
        self._maps.append(m if m is not None else {})

    def popmap(self) -> dict[Any, Any]:
        return self._maps.pop()

    def __setitem__(self, key: Any, value: Any) -> None:
        self._maps[-1][key] = value

    def __len__(self) -> int:
        return len(self._maps)


class ComputeEngine:
    __slots__ = ("_pending", "_protected")

    def __init__(self, pending_factory: type | None = None) -> None:
        self._pending: defaultdict[Any, set] = defaultdict(pending_factory or set)
        self._protected = _StackMap()

    @property
    def pending(self) -> defaultdict[Any, set]:
        return self._pending

    def schedule(self, field: Any, ids: Iterable) -> None:
        existing = self._pending.get(field)
        if existing is None:
            ids = list(ids)
            if not ids:
                return
            existing = self._pending[field]
        existing.update(ids)

    def mark_done(self, field: Any, ids: Iterable) -> None:
        pending = self._pending.get(field)
        if pending is None:
            return
        pending.difference_update(ids)
        if not pending:
            del self._pending[field]

    def is_pending(self, field: Any, record_id: Any) -> bool:
        return record_id in self._pending.get(field, ())

    def pending_ids(self, field: Any) -> set | tuple:
        return self._pending.get(field, ())

    def pending_fields(self) -> Collection[Any]:
        return self._pending.keys()

    def has_pending(self) -> bool:
        return bool(self._pending)

    def has_pending_field(self, field: Any) -> bool:
        return field in self._pending

    def pending_real_fields(self) -> list[Any]:
        return [field for field, ids in self._pending.items() if any(ids)]

    def discard_field(self, field: Any) -> None:
        self._pending.pop(field, None)

    def is_protected(self, field: Any, record_id: Any) -> bool:
        return record_id in (self._protected.get(field) or ())

    def protected_ids(self, field: Any) -> frozenset:
        return self._protected.get(field) or frozenset()

    def push_protection(self) -> None:
        self._protected.pushmap()

    def pop_protection(self) -> dict[Any, Any]:
        return self._protected.popmap()

    def protect(self, field: Any, ids: frozenset) -> None:
        existing = self._protected.get(field)
        self._protected[field] = existing.union(ids) if existing else ids

    def clear(self) -> None:
        self._pending.clear()

    def __repr__(self) -> str:
        n_fields = len(self._pending)
        n_entries = sum(len(ids) for ids in self._pending.values())
        n_scopes = len(self._protected)
        return f"<ComputeEngine pending={n_fields}f/{n_entries}e scopes={n_scopes}>"
