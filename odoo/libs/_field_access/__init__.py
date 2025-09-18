"""Field cache access accelerator with pure-Python fallback."""

__all__ = [
    "ACCELERATED",
    "batch_cache_fill",
    "batch_cache_filter",
    "batch_cache_get",
    "batch_cache_values",
    "batch_group_ids",
    "scalar_cache_get",
    "sort_ids_by_values",
]

ACCELERATED: bool

# scalar_cache_get always uses the Python fallback — the hit path (3 dict
# subscripts) compiles to C-level PyDict_GetItem via BINARY_SUBSCR and is
# faster than calling into Rust due to PyO3 function-call boundary overhead
# (~35ns).  The batch functions amortize that cost over N iterations.
from ._fallback import scalar_cache_get  # type: ignore[assignment]

try:
    from odoo_rust import (  # type: ignore[import-untyped]
        batch_cache_fill,
        batch_cache_filter,
        batch_cache_get,
        batch_cache_values,
        batch_group_ids,
        sort_ids_by_values,
    )

    ACCELERATED = True

except ImportError:
    from ._fallback import (  # type: ignore[assignment]
        batch_cache_fill,
        batch_cache_filter,
        batch_cache_get,
        batch_cache_values,
        batch_group_ids,
        sort_ids_by_values,
    )

    ACCELERATED = False
