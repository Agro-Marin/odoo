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
