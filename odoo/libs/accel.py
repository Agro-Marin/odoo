"""The accelerated primitives, native when odoo_rust is importable and pure Python otherwise.

One seam: every call site imports from here (or from ``odoo.libs._field_access``, which
resolves its own seven names the same way), so whether the process runs on the
extension is decided once. The pure versions are the references the parity and
timing tests measure the extension against; ``NATIVE`` says which side is live.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import cast

try:
    import odoo_rust as _native
except ImportError:
    _native = None

NATIVE = _native is not None

__all__ = [
    "NATIVE",
    "batch_cache_fill",
    "batch_cache_filter",
    "batch_cache_get",
    "batch_group_ids",
    "csv_export",
    "fast_clone",
    "origin_ids",
    "rows_to_dicts",
    "sort_ids_by_cache",
    "to_prefetch_ids",
]

_FORMULA_PREFIXES = ("=", "-", "+", "@", "\t", "\r")


def csv_export_python(headers: Sequence, rows: Iterable[Sequence]) -> bytes:
    fp = io.StringIO()
    writer = csv.writer(fp, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    for row in rows:
        cells = []
        for value in row:
            if value is None or value is False:
                value = ""
            elif isinstance(value, bytes):
                value = value.decode()
            if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return fp.getvalue().encode()


def rows_to_dicts_python(names: Sequence[str], rows: Iterable[Sequence]) -> list[dict]:
    return [dict(zip(names, row, strict=True)) for row in rows]


def fast_clone_python[T](obj: T) -> T:
    if isinstance(obj, dict):
        return cast("T", {key: fast_clone_python(value) for key, value in obj.items()})
    if isinstance(obj, list):
        return cast("T", [fast_clone_python(value) for value in obj])
    if isinstance(obj, tuple):
        return cast("T", tuple(fast_clone_python(value) for value in obj))
    return obj


def origin_ids_python(ids: Iterable) -> tuple[int, ...]:
    return tuple(oid for id_ in ids if (oid := id_ or getattr(id_, "origin", None)))


def _pick[F](name: str, python: F) -> F:
    return getattr(_native, name) if _native is not None else python


csv_export = _pick("csv_export", csv_export_python)
rows_to_dicts = _pick("rows_to_dicts", rows_to_dicts_python)
fast_clone = _pick("fast_clone", fast_clone_python)
origin_ids = _pick("origin_ids", origin_ids_python)

from ._field_access import (  # noqa: E402  the field-access facade resolves its own names
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_group_ids,
    sort_ids_by_cache,
    to_prefetch_ids,
)
