"""Odoo-agnostic numeric utilities.

Pure Python numeric helpers with no Odoo dependencies.
"""

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
    round,  # re-export; deliberately absent from __all__, see below
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
"""``round`` is re-exported above but deliberately kept out of ``__all__``.

It shadows the builtin, so ``from odoo.libs.numbers import *`` must not pull it
in.  It is exported at all because the area is the public boundary
(``libs_facade_check``): ``odoo.tools.float_utils`` keeps upstream's
``float_utils.round`` reachable, and without this line it could only do so by
reaching past the area into the leaf module, which the gate refuses.
"""
