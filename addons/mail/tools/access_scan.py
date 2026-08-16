__all__ = ["scan_accessible_ids"]

import typing
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from odoo.tools import Query

if typing.TYPE_CHECKING:
    from odoo import models
    from odoo.api import DomainType


def scan_accessible_ids(
    model: models.BaseModel,
    domain: DomainType,
    offset: int,
    limit: int | None,
    order: str | None,
    base_search: Callable[..., Query],
    *,
    fetch: Callable[[Query], Sequence[Sequence[Any]]],
    allowed: Callable[[Sequence[Sequence[Any]]], Iterable[int]],
    chunk_min: int,
    chunk_max: int,
    tiebreak: str = "id ASC",
    **kwargs,
) -> list[int]:
    scan_order = order
    if order and not any(term.strip().split()[0] == "id" for term in order.split(",")):
        scan_order = f"{order}, {tiebreak}"

    target = offset + limit if limit else None
    chunk = None if target is None else min(max(target, chunk_min), chunk_max)

    ordered: list[int] = []
    seen: set[int] = set()
    sql_offset = 0
    while True:
        query = base_search(
            domain, offset=sql_offset, limit=chunk, order=scan_order, **kwargs
        )
        rows = fetch(query)
        chunk_allowed = set(allowed(rows))
        for row in rows:
            id_ = row[0]
            if id_ in chunk_allowed and id_ not in seen:
                seen.add(id_)
                ordered.append(id_)

        got = len(rows)
        sql_offset += got
        if target is None or len(ordered) >= target or got < chunk:
            break
        chunk = min(chunk * 2, chunk_max)

    return ordered[offset:target]
