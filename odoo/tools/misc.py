"""
Miscellaneous tools used by Odoo.

This module re-exports utilities from specialized modules for backward compatibility.

.. deprecated:: 19.0
    New code should import from the canonical locations listed below.

CANONICAL IMPORT LOCATIONS
==========================

+----------------------------------+------------------------------------------+
| Function/Class                   | Canonical Import                         |
+==================================+==========================================+
| **File Operations**                                                         |
+----------------------------------+------------------------------------------+
| file_path                        | from odoo.tools.files import ...         |
| file_open                        | from odoo.tools.files import ...         |
| file_open_temporary_directory    | from odoo.tools.files import ...         |
+----------------------------------+------------------------------------------+
| **Locale & Language**                                                       |
+----------------------------------+------------------------------------------+
| get_lang                         | from odoo.tools.locale_utils import ...  |
| get_iso_codes                    | from odoo.tools.locale_utils import ...  |
| scan_languages                   | from odoo.tools.locale_utils import ...  |
| babel_locale_parse               | from odoo.tools.locale_utils import ...  |
| posix_to_ldml, POSIX_TO_LDML     | from odoo.libs.locale import ...         |
+----------------------------------+------------------------------------------+
| **Formatting**                                                              |
+----------------------------------+------------------------------------------+
| formatLang                       | from odoo.tools.formatting import ...    |
| format_date, parse_date          | from odoo.tools.formatting import ...    |
| format_datetime, format_time     | from odoo.tools.formatting import ...    |
| format_amount, format_duration   | from odoo.tools.formatting import ...    |
| format_decimalized_number        | from odoo.tools.formatting import ...    |
| DEFAULT_SERVER_*_FORMAT          | from odoo.tools.formatting import ...    |
+----------------------------------+------------------------------------------+
| **Collections**                                                             |
+----------------------------------+------------------------------------------+
| OrderedSet, LastOrderedSet       | from odoo.libs.collections import ...    |
| frozendict, freehash             | from odoo.libs.collections import ...    |
| Collector, StackMap              | from odoo.libs.collections import ...    |
| ConstantMapping, ReadonlyDict    | from odoo.libs.collections import ...    |
| DotDict, submap                  | from odoo.libs.collections import ...    |
+----------------------------------+------------------------------------------+
| **Iteration**                                                               |
+----------------------------------+------------------------------------------+
| groupby, unique, partition       | from odoo.libs.iteration import ...      |
| topological_sort, merge_sequences| from odoo.libs.iteration import ...      |
| split_every                      | from odoo.libs.iteration import ...      |
| Sentinel, SENTINEL, PENDING      | from odoo.libs.iteration import ...      |
+----------------------------------+------------------------------------------+
| **Text Processing**                                                         |
+----------------------------------+------------------------------------------+
| remove_accents, human_size       | from odoo.libs.text import ...           |
| street_split, ADDRESS_REGEX      | from odoo.libs.text import ...           |
| str2bool, mod10r, get_flag       | from odoo.libs.text import ...           |
+----------------------------------+------------------------------------------+
| **Security**                                                                |
+----------------------------------+------------------------------------------+
| hmac, hash_sign                  | from odoo.tools.security import ...      |
| verify_hash_signed, consteq      | from odoo.tools.security import ...      |
| limited_field_access_token       | from odoo.tools.security import ...      |
+----------------------------------+------------------------------------------+
| **Subprocess & System**                                                     |
+----------------------------------+------------------------------------------+
| find_in_path, find_pg_tool       | from odoo.tools.subprocess import ...    |
| exec_pg_environ, real_time       | from odoo.tools.subprocess import ...    |
| stripped_sys_argv, dumpstacks    | from odoo.tools.subprocess import ...    |
+----------------------------------+------------------------------------------+
| **Logging**                                                                 |
+----------------------------------+------------------------------------------+
| mute_logger, lower_logging       | from odoo.libs.logging import ...        |
| unquote                          | from odoo.libs.logging import ...        |
+----------------------------------+------------------------------------------+
| **Utilities**                                                               |
+----------------------------------+------------------------------------------+
| discardattr, is_list_of          | from odoo.libs.utils import ...          |
| has_list_types, format_frame     | from odoo.libs.utils import ...          |
| replace_exceptions               | from odoo.libs.utils import ...          |
+----------------------------------+------------------------------------------+

DEFINED IN THIS MODULE (not re-exports)
=======================================
- Callbacks: callback queue for pre/post commit hooks
- clean_context: remove default_* keys from context dict
- get_diff: HTML diff between two texts

RE-EXPORTED FROM libs
=====================
- html_escape: from odoo.libs.text.html (canonical: markupsafe.escape)
- SKIPPED_ELEMENT_TYPES: from odoo.libs.xml
- default_parser: from odoo.libs.xml (which also installs the hardened
  lxml global defaults, formerly configured here as an import side effect)
"""

import collections
import typing
from difflib import HtmlDiff

from odoo.libs import xml as xml_lib

from odoo.libs.collections import (
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

from odoo.libs.iteration import (
    PENDING,
    SENTINEL,
    Sentinel,
    groupby,
    merge_sequences,
    partition,
    split_every,
    topological_sort,
    unique,
)

from odoo.libs.locale import (
    POSIX_TO_LDML,
    posix_to_ldml,
)

from odoo.libs.logging import (
    lower_logging,
    mute_logger,
    unquote,
)

from odoo.libs.text import (
    ADDRESS_REGEX,
    get_flag,
    human_size,
    mod10r,
    remove_accents,
    str2bool,
    street_split,
)

from odoo.libs.utils import (
    discardattr,
    format_frame,
    has_list_types,
    is_list_of,
    named_to_positional_printf,
    replace_exceptions,
)

from .files import (
    file_open,
    file_open_temporary_directory,
    file_path,
)

from .formatting import (
    DATE_LENGTH,
    DATETIME_FORMATS_MAP,
    DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_DATETIME_FORMAT,
    DEFAULT_SERVER_TIME_FORMAT,
    NON_BREAKING_SPACE,
    _format_time_ago,
    format_amount,
    format_date,
    format_datetime,
    format_decimalized_amount,
    format_decimalized_number,
    format_duration,
    format_time,
    formatLang,
    parse_date,
)

from .locale_utils import (
    babel_locale_parse,
    get_iso_codes,
    get_lang,
    scan_languages,
)

from .security import (
    consteq,
    hash_sign,
    hmac,
    limited_field_access_token,
    verify_hash_signed,
    verify_limited_field_access_token,
)

from .subprocess import (
    dumpstacks,
    exec_pg_environ,
    find_in_path,
    find_pg_tool,
    real_time,
    stripped_sys_argv,
)

if typing.TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "DEFAULT_SERVER_DATETIME_FORMAT",
    "DEFAULT_SERVER_DATE_FORMAT",
    "DEFAULT_SERVER_TIME_FORMAT",
    "NON_BREAKING_SPACE",
    "SKIPPED_ELEMENT_TYPES",
    "DotDict",
    "LastOrderedSet",
    "OrderedSet",
    "babel_locale_parse",
    "clean_context",
    "consteq",
    "discardattr",
    "file_open",
    "file_open_temporary_directory",
    "file_path",
    "find_in_path",
    "formatLang",
    "format_amount",
    "format_date",
    "format_datetime",
    "format_duration",
    "format_time",
    "frozendict",
    "get_iso_codes",
    "get_lang",
    "groupby",
    "hash_sign",
    "hmac",
    "html_escape",
    "human_size",
    "is_list_of",
    "merge_sequences",
    "mod10r",
    "mute_logger",
    "parse_date",
    "partition",
    "posix_to_ldml",
    "real_time",
    "remove_accents",
    "replace_exceptions",
    "split_every",
    "str2bool",
    "street_split",
    "topological_sort",
    "unique",
    "verify_hash_signed",
]

SKIPPED_ELEMENT_TYPES = xml_lib.SKIPPED_ELEMENT_TYPES

default_parser = xml_lib.default_parser


def clean_context(context: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Return a copy of ``context`` without keys starting with ``default_``."""
    return {k: v for k, v in context.items() if not k.startswith("default_")}


class Callbacks:
    """A simple queue of callback functions.  Upon run, every function is
    called (in addition order), and the queue is emptied.

    ::

        callbacks = Callbacks()


        # add foo
        def foo():
            print("foo")


        callbacks.add(foo)


        # add bar
        @callbacks.add
        def bar():
            print("bar")


        # add foo again
        callbacks.add(foo)

        # call foo(), bar(), foo(), then clear the callback queue
        callbacks.run()

    The queue also provides a ``data`` dictionary, that may be freely used to
    store anything, but is mostly aimed at aggregating data for callbacks.  The
    dictionary is automatically cleared by ``run()`` once all callback functions
    have been called.

    ::

        # register foo to process aggregated data
        @callbacks.add
        def foo():
            print(sum(callbacks.data["foo"]))


        callbacks.data.setdefault("foo", []).append(1)
        ...
        callbacks.data.setdefault("foo", []).append(2)
        ...
        callbacks.data.setdefault("foo", []).append(3)

        # call foo(), which prints 6
        callbacks.run()

    Given the global nature of ``data``, the keys should identify in a unique
    way the data being stored.  It is recommended to use strings with a
    structure like ``"{module}.{feature}"``.
    """

    __slots__ = ["_funcs", "data"]

    def __init__(self):
        self._funcs: collections.deque[Callable] = collections.deque()
        self.data = {}

    def add(self, func: Callable) -> None:
        """Add the given function."""
        self._funcs.append(func)

    def run(self) -> None:
        """Call all the functions (in addition order), then clear associated data."""
        while self._funcs:
            func = self._funcs.popleft()
            func()
        self.clear()

    def clear(self) -> None:
        """Remove all callbacks and data from self."""
        self._funcs.clear()
        self.data.clear()

    def __len__(self) -> int:
        return len(self._funcs)


from odoo.libs.text import html_escape


def get_diff(
    data_from: tuple[str, str],
    data_to: tuple[str, str],
    custom_style: str | bool = False,
    dark_color_scheme: bool = False,
) -> str:
    """Return, in an HTML table, the diff between two texts.

    :param data_from: tuple(text, name), name will be used as table header
    :param data_to: tuple(text, name), name will be used as table header
    :param custom_style: CSS string including <style> tag, or False for default style
    :param dark_color_scheme: True if dark color scheme is used
    :return: the diff as an HTML table.
    """

    def handle_style(
        html_diff: str, custom_style: str | bool, dark_color_scheme: bool
    ) -> str:
        """Append BS4 classes to the identifying classes HtmlDiff puts on the
        DOM, and add custom style so the table fits the modal width.

        The rewrites below match the *full attribute* including its leading
        space, not the bare word.  ``HtmlDiff`` escapes every space in the
        compared text to ``&nbsp;``, so a raw space can only occur inside a tag
        it generated -- which makes these patterns unable to match content.

        Matching bare words corrupted the very thing being diffed: the only two
        callers compare view arch (``base.reset_view_arch``) and server-action
        Python (``base.server_action_history``), and a stray ``.replace(
        "nowrap", "")`` silently deleted that word from the rendered diff, so
        ``style="white-space: nowrap"`` was shown to the user as
        ``style="white-space: "``.  Same hazard for ``diff_header``/
        ``diff_next`` appearing in the compared text.
        """
        to_append = {
            'class="diff_header"': "bg-600 text-light text-center align-top px-2",
            'class="diff_next"': "d-none",
        }
        for attribute, classes in to_append.items():
            html_diff = html_diff.replace(
                f" {attribute}", ' %s %s"' % (attribute[:-1], classes)
            )
        html_diff = html_diff.replace(' nowrap="nowrap"', "")
        colors = (
            ("#7f2d2f", "#406a2d", "#51232f", "#3f483b")
            if dark_color_scheme
            else ("#ffc1c0", "#abf2bc", "#ffebe9", "#e6ffec")
        )
        html_diff += (
            custom_style
            or """
            <style>
                .modal-dialog.modal-lg:has(table.diff) {
                    max-width: 1600px;
                    padding-left: 1.75rem;
                    padding-right: 1.75rem;
                }
                table.diff { width: 100%%; }
                table.diff th.diff_header { width: 50%%; }
                table.diff td.diff_header { white-space: nowrap; }
                table.diff td.diff_header + td { width: 50%%; }
                table.diff td { word-break: break-all; vertical-align: top; }
                table.diff .diff_chg, table.diff .diff_sub, table.diff .diff_add {
                    display: inline-block;
                    color: inherit;
                }
                table.diff .diff_sub, table.diff td:nth-child(3) > .diff_chg { background-color: %s }
                table.diff .diff_add, table.diff td:nth-child(6) > .diff_chg { background-color: %s }
                table.diff td:nth-child(3):has(>.diff_chg, .diff_sub) { background-color: %s }
                table.diff td:nth-child(6):has(>.diff_chg, .diff_add) { background-color: %s }
            </style>
        """
            % colors
        )
        return html_diff

    diff = HtmlDiff(tabsize=2).make_table(
        data_from[0].splitlines(),
        data_to[0].splitlines(),
        data_from[1],
        data_to[1],
        context=True,
        numlines=3,
    )
    return handle_style(diff, custom_style, dark_color_scheme)
