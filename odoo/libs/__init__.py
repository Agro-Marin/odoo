"""Odoo-agnostic libraries and utilities.

This package contains framework-agnostic utilities with NO dependency on the
Odoo framework (models, env, cursors), usable independently of it.  Several are
backed by the ``odoo_rust`` native extension, which is a HARD requirement of
this fork (enforced in ``odoo.init``); there is no Python fallback.

Subpackages:
    - collections: Data structures (OrderedSet, frozendict, Collector, etc.)
    - colors: Color conversion utilities (hex_to_rgb, rgb_to_hex, etc.)
    - datetime: Date/time utilities (date_range, start_of, end_of, etc.)
    - email: Email parsing/formatting (email_normalize, formataddr, etc.)
    - filesystem: File system utilities (appdirs, osutil, mimetypes, etc.)
    - image: Image utilities (image_fix_orientation, image_to_base64, etc.)
    - iteration: Iteration helpers (groupby, unique, topological_sort, etc.)
    - json: JSON utilities (scriptsafe encoding for HTML)
    - locale: Locale conversion utilities (py_to_js_locale, posix_to_ldml)
    - numbers: Numeric utilities (float_round, float_compare, etc.)
    - profiling: Performance profiling tools (speedscope, sourcemap)
    - sql: SQL string utilities (escape_psql, make_identifier, etc.)
    - text: Text processing (remove_accents, human_size, street_split, etc.)
    - web: Web utilities (urls)
    - xml: XML utilities (remove_control_characters, create_xml_node, etc.)
"""

# Collections
from .collections import (
    OrderedSet,
    LastOrderedSet,
    frozendict,
    freehash,
    Collector,
    StackMap,
    ReversedIterable,
    ConstantMapping,
    ReadonlyDict,
    DotDict,
    submap,
)

# Iteration
from .iteration import (
    groupby,
    unique,
    partition,
    topological_sort,
    merge_sequences,
    Sentinel,
    SENTINEL,
    split_every,
)

# Text
from .text import (
    remove_accents,
    human_size,
    street_split,
    ADDRESS_REGEX,
    str2bool,
    mod10r,
    get_flag,
)

# Utils
from .utils import (
    discardattr,
    is_list_of,
    has_list_types,
    format_frame,
    named_to_positional_printf,
    replace_exceptions,
)

__all__ = [
    "ADDRESS_REGEX",
    "SENTINEL",
    "Collector",
    "ConstantMapping",
    "DotDict",
    "LastOrderedSet",
    # Collections
    "OrderedSet",
    "ReadonlyDict",
    "ReversedIterable",
    "Sentinel",
    "StackMap",
    # Utils
    "discardattr",
    "format_frame",
    "freehash",
    "frozendict",
    "get_flag",
    # Iteration
    "groupby",
    "has_list_types",
    "human_size",
    "is_list_of",
    "merge_sequences",
    "mod10r",
    "named_to_positional_printf",
    "partition",
    # Text
    "remove_accents",
    "replace_exceptions",
    "split_every",
    "str2bool",
    "street_split",
    "submap",
    "topological_sort",
    "unique",
]
