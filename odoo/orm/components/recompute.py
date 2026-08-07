from __future__ import annotations

import typing
from collections import defaultdict
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Container, Mapping
    from collections.abc import Set as AbstractSet

    from ._protocols import SchedulableField
    from .compute import ComputeEngine


class RecomputeScheduler:
    __slots__ = (
        "_engine",
        "_inline",
        "_marked",
        "_seen_recursive",
        "to_invalidate",
        "to_recompute",
    )

    def __init__(
        self,
        compute_engine: ComputeEngine,
        marked: Mapping | None = None,
        *,
        schedule_inline: bool = False,
        set_factory: type | None = None,
    ) -> None:
        self._engine = compute_engine
        self._marked: Mapping = marked if marked is not None else {}
        self._inline = schedule_inline
        self._seen_recursive: dict[Any, set] = defaultdict(set)
        self.to_recompute: dict[Any, set] = defaultdict(set_factory or set)
        self.to_invalidate: list[tuple[Any, frozenset]] = []

    def process_entry(
        self,
        field: SchedulableField,
        ids: AbstractSet,
        cached_ids: Container | None = None,
    ) -> frozenset:
        protected = self._engine.protected_ids(field)
        if protected:
            ids = ids - protected  # noqa: PLR6104  `ids` is caller-owned: -= would mutate it in place
        if not ids:
            return frozenset()

        recursive_ids: frozenset = frozenset()
        if field.recursive:
            if field.is_stored_computed:
                m = self._marked.get(field)
                if m:
                    ids = ids - m  # noqa: PLR6104  caller-owned set, see above
                r = self.to_recompute.get(field)
                if r and ids:
                    ids = ids - r  # noqa: PLR6104  caller-owned set, see above
            else:
                seen = self._seen_recursive.get(field)
                if seen:
                    ids = ids - seen  # noqa: PLR6104  caller-owned set, see above
                if cached_ids is not None and ids:
                    ids = type(ids)(id_ for id_ in ids if id_ in cached_ids)
            if not ids:
                return frozenset()
            if not field.is_stored_computed:
                self._seen_recursive[field].update(ids)
            recursive_ids = frozenset(ids)

        if field.is_stored_computed:
            self.to_recompute[field].update(ids)
            if self._inline:
                self._engine.schedule(field, ids)
        else:
            self.to_invalidate.append((field, frozenset(ids)))

        return recursive_ids

    def __repr__(self) -> str:
        n_recompute = sum(len(ids) for ids in self.to_recompute.values())
        n_invalidate = sum(len(ids) for _, ids in self.to_invalidate)
        return (
            f"<RecomputeScheduler "
            f"recompute={len(self.to_recompute)}f/{n_recompute}e "
            f"invalidate={len(self.to_invalidate)}f/{n_invalidate}e>"
        )
