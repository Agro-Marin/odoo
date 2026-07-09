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
