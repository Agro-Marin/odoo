from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from .cache import _MISSING, FieldCache
from .compute import ComputeEngine
from .recompute import RecomputeScheduler

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping


class OrmCore:
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
        cache: FieldCache | None = None,
        engine: ComputeEngine | None = None,
    ) -> None:
        self._cache = cache if cache is not None else FieldCache()
        self._engine = engine if engine is not None else ComputeEngine()

    def get_value(self, field: Any, record_id: Any, default: Any = _MISSING) -> Any:
        """Return the cached value for ``(field, record_id)``.

        Falls back to ``default``, or raises ``KeyError`` when it is absent.
        """
        if default is _MISSING:
            return self._cache.get_value(field, record_id)
        return self._cache.get_value(field, record_id, default)

    def set_value(self, field: Any, record_id: Any, value: Any) -> None:
        """Seed one ``(field, record_id)`` entry.

        The counterpart to ``get_value`` above, and added for the same reason:
        the surviving raw-cache reaches were the ones the facade did not expose.
        The measurement that found two ``get_value`` reaches scanned only what
        the DB-free tiers exercise; two more sites reached
        ``_core.cache.set_value`` from **DB-backed** addon tests
        (``base/tests/test_orm.py``, ``base/tests/test_translate.py``), which
        `pytest` never runs -- so renaming the slot to ``_cache`` left them
        raising ``AttributeError``, visible only in the `--test-tags /base`
        integration lane.
        """
        self._cache.set_value(field, record_id, value)

    def get_field_data(self, field: Any) -> dict[Any, Any]:
        return self._cache.get_field_data(field)

    def get_field_data_or_none(self, field: Any) -> dict[Any, Any] | None:
        return self._cache.get_field_data_or_none(field)

    def invalidate(
        self,
        field: Any,
        ids: Iterable | None = None,
        *,
        context_dependent: bool,
        keep_dirty: bool = False,
    ) -> None:
        self._cache.invalidate(
            field, ids, context_dependent=context_dependent, keep_dirty=keep_dirty
        )

    def all_cached_ids(
        self, field: Any, *, context_dependent: bool
    ) -> Mapping[Any, Any]:
        return self._cache.all_cached_ids(field, context_dependent=context_dependent)

    def iter_context_caches(self, field: Any) -> Iterator[tuple[tuple, dict]]:
        return self._cache.iter_context_caches(field)

    def mark_dirty(self, field: Any, ids: Iterable) -> None:
        self._cache.mark_dirty(field, ids)

    def get_dirty(self, field: Any) -> set | None:
        return self._cache.get_dirty(field)

    def pop_dirty(self, field: Any) -> set | None:
        return self._cache.pop_dirty(field)

    def pop_dirty_for_model(self, model_name: str) -> dict[Any, set]:
        return self._cache.pop_dirty_for_model(model_name)

    def has_dirty_field(self, field: Any) -> bool:
        return self._cache.has_dirty_field(field)

    def is_any_dirty(self) -> bool:
        return self._cache.is_any_dirty()

    def find_pending_write(
        self, fields: Iterable[Any], ids: Iterable | None
    ) -> tuple[Any, list] | None:
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

    def add_patch(self, field: Any, record_id: Any, new_id: Any) -> None:
        self._cache.add_patch(field, record_id, new_id)

    def get_patches(self, field: Any) -> dict[Any, list] | None:
        return self._cache.get_patches(field)

    def iter_field_items(self) -> Iterator[tuple[Any, dict[Any, Any]]]:
        return self._cache.iter_field_items()

    def schedule(self, field: Any, ids: Iterable) -> None:
        self._engine.schedule(field, ids)

    def new_scheduler(self, *, inline: bool = False) -> RecomputeScheduler:
        return RecomputeScheduler(
            self._engine,
            marked=self._engine.pending,
            schedule_inline=inline,
            set_factory=self._engine.pending.default_factory,
        )

    def mark_done(self, field: Any, ids: Iterable) -> None:
        self._engine.mark_done(field, ids)

    def is_pending(self, field: Any, record_id: Any) -> bool:
        return self._engine.is_pending(field, record_id)

    def has_pending_field(self, field: Any) -> bool:
        return self._engine.has_pending_field(field)

    def has_pending(self) -> bool:
        return self._engine.has_pending()

    def pending_ids(self, field: Any) -> set | tuple:
        return self._engine.pending_ids(field)

    def pending_fields(self) -> Collection[Any]:
        return self._engine.pending_fields()

    def discard_field(self, field: Any) -> None:
        self._engine.discard_field(field)

    def is_protected(self, field: Any, record_id: Any) -> bool:
        return self._engine.is_protected(field, record_id)

    def protected_ids(self, field: Any) -> frozenset:
        return self._engine.protected_ids(field)

    def push_protection(self) -> None:
        self._engine.push_protection()

    def pop_protection(self) -> dict[Any, Any]:
        return self._engine.pop_protection()

    def protect(self, field: Any, ids: frozenset) -> None:
        self._engine.protect(field, ids)

    def clear_cache(self) -> None:
        self._cache.clear()

    def __repr__(self) -> str:
        return f"<OrmCore {self._cache!r} {self._engine!r}>"
