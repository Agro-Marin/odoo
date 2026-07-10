"""Odoo-agnostic collection utilities.

These are pure Python data structures with no Odoo dependencies.
"""

from .ordered_set import OrderedSet, LastOrderedSet
from .frozen_dict import frozendict, freehash
from .misc import Collector, StackMap, ReversedIterable
from .mappings import ConstantMapping, ReadonlyDict, DotDict, submap

__all__ = [
    "Collector",
    "ConstantMapping",
    "DotDict",
    "LastOrderedSet",
    "OrderedSet",
    "ReadonlyDict",
    "ReversedIterable",
    "StackMap",
    "freehash",
    "frozendict",
    "submap",
]
