"""Fast deep clone for JSON-like data structures.

Backed by the Rust ``odoo_rust`` extension (~5x faster than ``copy.deepcopy``):
it skips the ``__deepcopy__`` protocol and the memo dict.  Safe for data from
``json.loads()`` or destined for ``json.dumps()`` (dict/list/tuple of
str/int/float/bool/None).

It keeps no memo, so it cannot *dedupe* shared subtrees the way ``deepcopy``
does, and a genuinely **cyclic** structure (reachable because Json/Properties
field values are addon-writable) has no memo to break the loop — a bounded
recursion depth turns that, and pathologically deep input, into a
``RecursionError`` rather than a native stack overflow / segfault.
"""

from odoo_rust import fast_clone

__all__ = ["fast_clone"]
