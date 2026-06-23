"""Fast deep clone for JSON-like data structures.

Backed by the Rust ``odoo_rust`` extension (~5x faster than ``copy.deepcopy``):
it skips the ``__deepcopy__`` protocol, memo dict, and cycle detection.  Safe
for data from ``json.loads()`` or destined for ``json.dumps()`` (dict/list/tuple
of str/int/float/bool/None).
"""

from odoo_rust import fast_clone

__all__ = ["fast_clone"]
