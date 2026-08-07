__all__ = [
    "batch_cache_fill",
    "batch_cache_filter",
    "batch_cache_get",
    "batch_cache_values",
    "batch_group_ids",
    "scalar_cache_get",
    "sort_ids_by_cache",
    "sort_ids_by_values",
    "to_prefetch_ids",
]

from odoo_rust import (
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_cache_values,
    batch_group_ids,
    sort_ids_by_cache,
    sort_ids_by_values,
    to_prefetch_ids,
)

from ._fallback import scalar_cache_get
