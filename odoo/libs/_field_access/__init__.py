"""Field cache access accelerator (Rust-backed batch operations)."""

__all__ = [
    "batch_cache_fill",
    "batch_cache_filter",
    "batch_cache_get",
    "batch_cache_values",
    "batch_group_ids",
    "scalar_cache_get",
    "sort_ids_by_values",
]

from odoo_rust import (  # type: ignore[import-untyped]
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_cache_values,
    batch_group_ids,
    sort_ids_by_values,
)

# scalar_cache_get always uses the Python implementation: the hit path (3 dict
# subscripts) compiles to C-level PyDict_GetItem via BINARY_SUBSCR and beats the
# PyO3 call-boundary overhead (~35ns); the batch ops amortize that over N items.
from ._fallback import scalar_cache_get  # type: ignore[assignment]
