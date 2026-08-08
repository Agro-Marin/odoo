from .float_utils import (
    RoundingMethod,
    float_compare,
    float_invert,
    float_is_zero,
    float_repr,
    float_round,
    float_split,
    float_split_str,
    json_float_round,
)

__all__ = [
    "RoundingMethod",
    "float_compare",
    "float_invert",
    "float_is_zero",
    "float_repr",
    "float_round",
    "float_split",
    "float_split_str",
    "json_float_round",
]
"""``round`` is deliberately NOT re-exported here.

It shadows the builtin, so it was already kept out of ``__all__``; it was still
imported into this namespace so that ``odoo.tools.float_utils`` could reach it
through the area rather than past it into the leaf module, which
``libs_facade_check`` refuses.  That module was a two-line re-export shim with
no importer anywhere in ``odoo``, ``enterprise``, ``agromarin`` or
``design-themes`` -- its only rationale was keeping upstream's
``float_utils.round`` spelling reachable, and this fork carries no
backward-compatibility obligation to upstream.  Deleting it removed the sole
consumer, so the import went with it.  ``float_round`` is the fork's spelling.
"""
