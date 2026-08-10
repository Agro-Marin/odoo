from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, cast

from ._protocols import FieldKey
from .cache import _MISSING, FieldCache
from .compute import ComputeEngine
from .recompute import RecomputeScheduler

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping


class OrmCore[F: FieldKey = FieldKey]:
    # PRIVATE slots, public constructor kwargs. ADR-0010 describes this class as
    # a "curated id-level facade" over FieldCache/ComputeEngine and
    # ARCHITECTURE.md states that "the raw objects stay private to Transaction".
    # They were not: the slots were named `cache`/`engine`, so `env._core.cache`
    # WAS `transaction._cache_store` -- a public pass-through straight to the
    # object the facade exists to wrap. Measured before this change, 62 of the
    # 64 `_core.<attr>` accesses in odoo/ + addons/ used a curated method and
    # exactly 2 reached the raw cache, both for `get_value`, which the facade
    # simply did not expose. Adding it (below) closed the only real gap.
    #
    # The keyword names stay `cache=`/`engine=`: collaborator injection is the
    # ADR-0002 contract and Transaction plus the component unit tests pass them.
    __slots__ = ("_cache", "_engine")

    def __init__(
        self,
        cache: FieldCache[F] | None = None,
        engine: ComputeEngine[F] | None = None,
    ) -> None:
        # `cast` rather than a union: the fallbacks exist so a test can build
        # an OrmCore with no arguments, and an unparameterised FieldCache() is
        # `FieldCache[FieldKey]` -- which is precisely what `F` defaults to in
        # that case. Injecting real collaborators (ADR-0002) is the production
        # path and carries the real key type.
        self._cache: FieldCache[F] = (
            cache if cache is not None else cast("FieldCache[F]", FieldCache())
        )
        self._engine: ComputeEngine[F] = (
            engine if engine is not None else cast("ComputeEngine[F]", ComputeEngine())
        )

    def get_value(self, field: F, record_id: Any, default: Any = _MISSING) -> Any:
        if default is _MISSING:
            return self._cache.get_value(field, record_id)
        return self._cache.get_value(field, record_id, default)

    def set_value(self, field: F, record_id: Any, value: Any) -> None:
        self._cache.set_value(field, record_id, value)

    def get_field_data(self, field: F) -> dict[Any, Any]:
        return self._cache.get_field_data(field)

    def get_field_data_or_none(self, field: F) -> dict[Any, Any] | None:
        return self._cache.get_field_data_or_none(field)

    def invalidate(
        self,
        field: F,
        ids: Iterable[Any] | None = None,
        *,
        context_dependent: bool,
        keep_dirty: bool = False,
    ) -> None:
        self._cache.invalidate(
            field, ids, context_dependent=context_dependent, keep_dirty=keep_dirty
        )

    def all_cached_ids(self, field: F, *, context_dependent: bool) -> Mapping[Any, Any]:
        return self._cache.all_cached_ids(field, context_dependent=context_dependent)

    def iter_context_caches(self, field: F) -> Iterator[tuple[tuple, dict[Any, Any]]]:
        return self._cache.iter_context_caches(field)

    def mark_dirty(self, field: F, ids: Iterable[Any]) -> None:
        self._cache.mark_dirty(field, ids)

    def get_dirty(self, field: F) -> set[Any] | None:
        return self._cache.get_dirty(field)

    def pop_dirty(self, field: F) -> set[Any] | None:
        return self._cache.pop_dirty(field)

    def pop_dirty_for_model(self, model_name: str) -> dict[F, set[Any]]:
        return self._cache.pop_dirty_for_model(model_name)

    def has_dirty_field(self, field: F) -> bool:
        return self._cache.has_dirty_field(field)

    def is_any_dirty(self) -> bool:
        return self._cache.is_any_dirty()

    def find_pending_write(
        self, fields: Iterable[F], ids: Iterable[Any] | None
    ) -> tuple[F, list[Any]] | None:
        if isinstance(ids, Iterator):
            ids = tuple(ids)
        for field in fields:
            dirty_ids = self._cache.get_dirty(field)
            if not dirty_ids:
                continue
            if ids is None:
                return field, sorted(dirty_ids)
            overlap = sorted(dirty_ids.intersection(ids))
            if overlap:
                return field, overlap
        return None

    def add_patch(self, field: F, record_id: Any, new_id: Any) -> None:
        self._cache.add_patch(field, record_id, new_id)

    def get_patches(self, field: F) -> dict[Any, list[Any]] | None:
        return self._cache.get_patches(field)

    def iter_field_items(self) -> Iterator[tuple[F, dict[Any, Any]]]:
        return self._cache.iter_field_items()

    def schedule(self, field: F, ids: Iterable[Any]) -> None:
        self._engine.schedule(field, ids)

    def new_scheduler(self, *, inline: bool = False) -> RecomputeScheduler:
        return RecomputeScheduler(
            cast("ComputeEngine[FieldKey]", self._engine),
            marked=self._engine.pending,
            schedule_inline=inline,
            set_factory=self._engine.pending.default_factory,
        )

    def mark_done(self, field: F, ids: Iterable[Any]) -> None:
        self._engine.mark_done(field, ids)

    def is_pending(self, field: F, record_id: Any) -> bool:
        return self._engine.is_pending(field, record_id)

    def has_pending_field(self, field: F) -> bool:
        return self._engine.has_pending_field(field)

    def has_pending(self) -> bool:
        return self._engine.has_pending()

    def pending_ids(self, field: F) -> set[Any] | tuple[()]:
        return self._engine.pending_ids(field)

    def pending_fields(self) -> Collection[F]:
        return self._engine.pending_fields()

    def discard_field(self, field: F) -> None:
        self._engine.discard_field(field)

    def is_protected(self, field: F, record_id: Any) -> bool:
        return self._engine.is_protected(field, record_id)

    def protected_ids(self, field: F) -> frozenset[Any]:
        return self._engine.protected_ids(field)

    def push_protection(self) -> None:
        self._engine.push_protection()

    def pop_protection(self) -> dict[F, frozenset[Any]]:
        return self._engine.pop_protection()

    def protect(self, field: F, ids: frozenset[Any]) -> None:
        self._engine.protect(field, ids)

    def clear_cache(self) -> None:
        self._cache.clear()

    def __repr__(self) -> str:
        return f"<OrmCore {self._cache!r} {self._engine!r}>"
