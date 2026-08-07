from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from .cache import FieldCache
from .compute import ComputeEngine
from .recompute import RecomputeScheduler

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping


class OrmCore:
    __slots__ = ("cache", "engine")

    def __init__(
        self,
        cache: FieldCache | None = None,
        engine: ComputeEngine | None = None,
    ) -> None:
        self.cache = cache if cache is not None else FieldCache()
        self.engine = engine if engine is not None else ComputeEngine()

    def get_field_data(self, field: Any) -> dict[Any, Any]:
        return self.cache.get_field_data(field)

    def get_field_data_or_none(self, field: Any) -> dict[Any, Any] | None:
        return self.cache.get_field_data_or_none(field)

    def invalidate(
        self,
        field: Any,
        ids: Iterable | None = None,
        *,
        context_dependent: bool,
        keep_dirty: bool = False,
    ) -> None:
        self.cache.invalidate(
            field, ids, context_dependent=context_dependent, keep_dirty=keep_dirty
        )

    def all_cached_ids(
        self, field: Any, *, context_dependent: bool
    ) -> Mapping[Any, Any]:
        return self.cache.all_cached_ids(field, context_dependent=context_dependent)

    def iter_context_caches(self, field: Any) -> Iterator[tuple[tuple, dict]]:
        return self.cache.iter_context_caches(field)

    def mark_dirty(self, field: Any, ids: Iterable) -> None:
        self.cache.mark_dirty(field, ids)

    def get_dirty(self, field: Any) -> set | None:
        return self.cache.get_dirty(field)

    def pop_dirty(self, field: Any) -> set | None:
        return self.cache.pop_dirty(field)

    def pop_dirty_for_model(self, model_name: str) -> dict[Any, set]:
        return self.cache.pop_dirty_for_model(model_name)

    def has_dirty_field(self, field: Any) -> bool:
        return self.cache.has_dirty_field(field)

    def is_any_dirty(self) -> bool:
        return self.cache.is_any_dirty()

    def find_pending_write(
        self, fields: Iterable[Any], ids: Iterable | None
    ) -> tuple[Any, list] | None:
        if isinstance(ids, Iterator):
            ids = tuple(ids)
        for field in fields:
            dirty_ids = self.cache.get_dirty(field)
            if not dirty_ids:
                continue
            if ids is None:
                return field, sorted(dirty_ids)
            overlap = sorted(dirty_ids.intersection(ids))
            if overlap:
                return field, overlap
        return None

    def add_patch(self, field: Any, record_id: Any, new_id: Any) -> None:
        self.cache.add_patch(field, record_id, new_id)

    def get_patches(self, field: Any) -> dict[Any, list] | None:
        return self.cache.get_patches(field)

    def iter_field_items(self) -> Iterator[tuple[Any, dict[Any, Any]]]:
        return self.cache.iter_field_items()

    def schedule(self, field: Any, ids: Iterable) -> None:
        self.engine.schedule(field, ids)

    def new_scheduler(self, *, inline: bool = False) -> RecomputeScheduler:
        return RecomputeScheduler(
            self.engine,
            marked=self.engine.pending,
            schedule_inline=inline,
            set_factory=self.engine.pending.default_factory,
        )

    def mark_done(self, field: Any, ids: Iterable) -> None:
        self.engine.mark_done(field, ids)

    def is_pending(self, field: Any, record_id: Any) -> bool:
        return self.engine.is_pending(field, record_id)

    def has_pending_field(self, field: Any) -> bool:
        return self.engine.has_pending_field(field)

    def has_pending(self) -> bool:
        return self.engine.has_pending()

    def pending_ids(self, field: Any) -> set | tuple:
        return self.engine.pending_ids(field)

    def pending_fields(self) -> Collection[Any]:
        return self.engine.pending_fields()

    def discard_field(self, field: Any) -> None:
        self.engine.discard_field(field)

    def is_protected(self, field: Any, record_id: Any) -> bool:
        return self.engine.is_protected(field, record_id)

    def protected_ids(self, field: Any) -> frozenset:
        return self.engine.protected_ids(field)

    def push_protection(self) -> None:
        self.engine.push_protection()

    def pop_protection(self) -> dict[Any, Any]:
        return self.engine.pop_protection()

    def protect(self, field: Any, ids: frozenset) -> None:
        self.engine.protect(field, ids)

    def clear_cache(self) -> None:
        self.cache.clear()

    def __repr__(self) -> str:
        return f"<OrmCore {self.cache!r} {self.engine!r}>"
