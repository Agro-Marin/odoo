"""Odoo-agnostic utilities.

The names below are re-exported **lazily** (PEP 562). They used to be imported
eagerly, which made this module the single heaviest import in the framework for
reasons none of its consumers asked for: `.text` pulls `libs/text/html.py`,
which imports `lxml`, `lxml.html.clean`, `markupsafe` and `arabic_reshaper`. So

    from odoo.libs.collections import Collector      # a 30-line helper

executed the parent package first and dragged in the whole HTML sanitiser.

Measured, that reached further than a slow import. `odoo/orm/components/` is
contractually pure Python -- `layer_check`'s `orm-components-are-pure-python`,
whose stated purpose is that the cache/compute engine be "unit-testable without
an Environment, Registry, or database" -- and `components/model_graph.py` imports
`Collector` from here. A `sys.modules` diff around a single
`import odoo.orm.components.model_graph` showed **lxml, babel and markupsafe**
loaded. The gate could not see it: it inspects `odoo.*` import edges, and this
dependency arrives through a third party.

Lazy resolution fixes that at the root, for every consumer at once, without
moving a helper or weakening a contract: importing an area now costs that area.

The area packages remain the public boundary (`libs_facade_check`); this module
is a convenience surface over them, not a second one.
"""

import importlib
import typing

#: Which area provides each re-exported name -- the table `__getattr__` resolves
#: against. `__all__` below repeats these names as a literal, for the reason
#: given there; a test asserts the two agree as sets, so a name cannot be
#: advertised without being resolvable, or resolvable without being advertised.
_EXPORTS: dict[str, tuple[str, ...]] = {
    "collections": (
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
    ),
    "iteration": (
        "SENTINEL",
        "Sentinel",
        "groupby",
        "merge_sequences",
        "partition",
        "split_every",
        "topological_sort",
        "unique",
    ),
    "text": (
        "ADDRESS_REGEX",
        "get_flag",
        "human_size",
        "mod10r",
        "remove_accents",
        "str2bool",
        "street_split",
    ),
    "utils": (
        "discardattr",
        "format_frame",
        "has_list_types",
        "is_list_of",
        "named_to_positional_printf",
        "replace_exceptions",
    ),
}

_AREA_OF: dict[str, str] = {
    name: area for area, names in _EXPORTS.items() for name in names
}

#: Spelled out rather than derived from `_AREA_OF`: a computed `__all__` is
#: invisible to ruff, mypy and every IDE, which is exactly the wrong trade for a
#: public surface. `test_facade_is_lazy.test_all_matches_the_export_table` keeps
#: the two in agreement, so the literal cannot drift.
__all__ = [
    "ADDRESS_REGEX",
    "SENTINEL",
    "Collector",
    "ConstantMapping",
    "DotDict",
    "LastOrderedSet",
    "OrderedSet",
    "ReadonlyDict",
    "ReversedIterable",
    "Sentinel",
    "StackMap",
    "discardattr",
    "format_frame",
    "freehash",
    "frozendict",
    "get_flag",
    "groupby",
    "has_list_types",
    "human_size",
    "is_list_of",
    "merge_sequences",
    "mod10r",
    "named_to_positional_printf",
    "partition",
    "remove_accents",
    "replace_exceptions",
    "split_every",
    "str2bool",
    "street_split",
    "submap",
    "topological_sort",
    "unique",
]

if typing.TYPE_CHECKING:
    # Never executed; it exists so type checkers and IDEs still resolve the
    # names statically. Without it a module-level __getattr__ types every
    # re-export as Any, which would quietly weaken the mypy gate.
    from .collections import (
        Collector,
        ConstantMapping,
        DotDict,
        LastOrderedSet,
        OrderedSet,
        ReadonlyDict,
        ReversedIterable,
        StackMap,
        freehash,
        frozendict,
        submap,
    )
    from .iteration import (
        SENTINEL,
        Sentinel,
        groupby,
        merge_sequences,
        partition,
        split_every,
        topological_sort,
        unique,
    )
    from .text import (
        ADDRESS_REGEX,
        get_flag,
        human_size,
        mod10r,
        remove_accents,
        str2bool,
        street_split,
    )
    from .utils import (
        discardattr,
        format_frame,
        has_list_types,
        is_list_of,
        named_to_positional_printf,
        replace_exceptions,
    )


def __getattr__(name: str) -> typing.Any:
    area = _AREA_OF.get(name)
    if area is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{area}", __name__), name)
    # Cache in the module globals so every later read is an ordinary lookup and
    # never re-enters this function.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return __all__
