"""QWeb rendering engine (``ir.qweb``).

QWeb is Odoo's primary templating engine: an XML engine used mostly to generate
XML and HTML. Directives are XML attributes prefixed with ``t-`` (e.g. ``t-if``);
the placeholder ``<t>`` element runs its directives without emitting any output.
See https://www.odoo.com/documentation/master/developer/reference/frontend/qweb.html

Rendering
=========

``_compile`` turns an input etree into a python generator function that yields
output one chunk at a time; ``_render`` consumes it. Compilation runs once per
(template, options, language) set and is ormcached, so compile time matters far
less than render time. Output is ``MarkupSafe`` (escaped, injection-safe).

At compile time each ``t-*`` directive is compiled into python code and removed
from the node; no dynamic attribute may remain once a node is fully compiled.

How the code works
==================

Summary of the method calls in the IrQweb class:

.. code-block:: rst

    Odoo
     ┗━► _render (returns MarkupSafe)
        ┗━► _compile (returns function)                                        ◄━━━━━━━━━━┓
           ┗━► _compile_node (returns code string array)                       ◄━━━━━━━━┓ ┃
              ┃  (skip the current node if found t-qweb-skip)                           ┃ ┃
              ┃  (add technical directives: t-tag-open, t-tag-close, t-inner-content)   ┃ ┃
              ┃                                                                         ┃ ┃
              ┣━► _directives_eval_order (defined directive order)                      ┃ ┃
              ┣━► _compile_directives (loop)    Consume all remaining directives ◄━━━┓  ┃ ┃
              ┃  ┃                              (e.g.: to change the indentation)    ┃  ┃ ┃
              ┃  ┣━► _compile_directive                                              ┃  ┃ ┃
              ┃  ┃    ┗━► t-groups        ━━► _compile_directive_groups             ━┫  ┃ ┃
              ┃  ┃    ┗━► t-foreach       ━━► _compile_directive_foreach            ━┫  ┃ ┃
              ┃  ┃    ┗━► t-if            ━━► _compile_directive_if                 ━┛  ┃ ┃
              ┃  ┃    ┗━► t-inner-content ━━► _compile_directive_inner_content ◄━━━━━┓ ━┛ ┃
              ┃  ┃    ┗━► t-options       ━━► _compile_directive_options             ┃    ┃
              ┃  ┃    ┗━► t-set           ━━► _compile_directive_set           ◄━━┓  ┃    ┃
              ┃  ┃    ┗━► t-call          ━━► _compile_directive_call            ━┛ ━┫ ━━━┛
              ┃  ┃    ┗━► t-att           ━━► _compile_directive_att                 ┃
              ┃  ┃    ┗━► t-tag-open      ━━► _compile_directive_open          ◄━━┓  ┃
              ┃  ┃    ┗━► t-tag-close     ━━► _compile_directive_close         ◄━━┫  ┃
              ┃  ┃    ┗━► t-out           ━━► _compile_directive_out             ━┛ ━┫ ◄━━┓
              ┃  ┃    ┗━► t-field         ━━► _compile_directive_field               ┃   ━┫
              ┃  ┃    ┗━► t-esc           ━━► _compile_directive_esc                 ┃   ━┛
              ┃  ┃    ┗━► t-*             ━━► ...                                    ┃
              ┃  ┃                                                                   ┃
              ┗━━┻━► _compile_static_node                                           ━┛


Each XML node goes through ``_compile_node``. A node with no ``t-*`` attribute is
"static" (``_is_static_node``) and is compiled by ``_compile_static_node``;
otherwise ``_compile_directives`` compiles the directives in the order of
``_directives_eval_order``, dispatching each through ``_compile_directive`` to
``_compile_directive_<name>`` (e.g. ``t-if`` => ``_compile_directive_if``), then
compiles any directive attributes still on the element.

``_post_processing_att`` builds the rendering attributes — once at compile time
for static nodes, once per render otherwise. Each expression is compiled by
``_compile_expr`` into a namespaced python expression.

Directives
----------

``t-debug`` (values: ``''``, ``pdb``, ``ipdb``, ``pudb``, ``wdb``)
    Trigger a debugger breakpoint (dev mode only), giving access to the rendered
    variables. An empty value calls the ``breakpoint`` builtin; naming an explicit
    debugger is deprecated since 17.0 (configure ``PYTHONBREAKPOINT`` /
    ``sys.setbreakpointhook`` instead).

``t-if`` / ``t-elif`` / ``t-else`` (values: python expression; ``t-else`` none)
    Wrap the compiled content in a python ``if``/``elif``/``else``. ``t-elif`` and
    ``t-else`` are compiled together with the preceding ``t-if`` (not separately in
    ``_directives_eval_order``) and their nodes are marked not to render twice.

``t-groups`` (``groups`` is an alias)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Values**: allowed group name, ``!``-prefixed to prohibit

Wrap the content in a ``has_groups`` check (``res.users``).

``t-foreach``
~~~~~~~~~~~~~
**Values**: an expression returning the collection to iterate on

Convert to a ``for`` loop; ``t-as`` names the key. Also populates ``*_value``,
``*_index``, ``*_size``, ``*_first``, ``*_last`` (and ``*_odd``/``*_even``/
``*_parity``) in ``values``.

``t-as``
~~~~~~~~
**Values**: key name

Only validates that ``t-as`` and ``t-foreach`` are on the same node.

``t-options`` and ``t-options-*``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Values**: python expression

Configure a ``t-call``/``t-field``/``t-out`` on the same node by building
``values['__qweb_options__']``: ``t-options-widget="'float'"`` is merged as
``{'widget': 'float'}`` on top of the optional ``t-options`` dict.

``t-att``, ``t-att-*``, ``t-attf-*`` and ``t-attf-*.translate``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Values**: python expression (or format string expression for ``t-attf-``)

Build ``values['__qweb_attrs__']``. ``t-att`` is a dict expression, ``t-att-*`` a
python expression, ``t-attf-*`` a format string (translated when suffixed
``.translate``). New namespaces and static (non-``t-``) attributes are added too.

``t-call``
~~~~~~~~~~
**Values**: format string expression for template name

Render the called template in place of the ``t-call`` node, with a copy of
``values``; the node's content is compiled into a separate function and exposed
to the callee as the magic slot ``0`` (``t-out="0"``, updatable via ``t-set``).
``t-options`` configures the call.

``t-lang``
~~~~~~~~~~
**Values**: python expression

Alias of ``t-options-lang``, only valid with ``t-call``; renders the called
template in another language.

``t-call-assets``
~~~~~~~~~~~~~~~~~
**Values**: format string for template name

Aggregate/minify the bundle's JS/CSS via ``_get_asset_nodes``.

``t-out``
~~~~~~~~~
**Values**: python expression

Output the value, or the node content as default when falsy (e.g.
``<t t-out="given_value">Default content</t>``). With a widget
(``t-options-widget``) the value is formatted by ``_get_widget`` (an
``ir.qweb.field.*`` model).

``t-field``
~~~~~~~~~~~
**Values**: field path (for example ``t-field="record.name"``)

Like ``t-out`` but formatted by ``_get_field`` (an ``ir.qweb.field.*`` model)
according to the field type; overridable via ``t-options-widget``.

``t-esc``
~~~~~~~~~
Deprecated, please use ``t-out``

``t-raw``
~~~~~~~~~
Deprecated, please use ``t-out``

``t-set``
~~~~~~~~~
**Values**: key name

Assign ``values[key]`` from ``t-value`` (expression), ``t-valuef`` (format
string) or, absent those, the node's ``MarkupSafe`` content.

``t-value``, ``t-valuef`` and ``t-valuef.translate``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Values**: python expression (or format string expression)

Only validates that this directive and ``t-set`` are on the same node. The
format string can be translated with ``.translate``.


Technical directives
--------------------

Directive added automatically by IrQweb in order to go through the compilation
methods.

``t-tag-open``
~~~~~~~~~~~~~~
Used to generate the opening HTML/XML tags.

``t-tag-close``
~~~~~~~~~~~~~~
Used to generate the closing HTML/XML tags.

``t-inner-content``
~~~~~~~~~~~~~~~~~~~
Add the node's content (text, tail and children). Copies the options when the
element declares namespaces.

``t-consumed-options``
~~~~~~~~~~~~~~~~~~~~~~
Raise an exception if the ``t-options`` is not consumed.

``t-qweb-skip``
~~~~~~~~~~~~~~~~~~~~~~
Ignore rendering and directives for the current **input** node.

``t-else-valid``
~~~~~~~~~~~~~~~~~~~~~~
Mark a node with ``t-else`` or ``t-elif`` having a valid **input** dom
structure.

"""

import ast
import base64
import io
import logging
import math
import pprint
import re
import textwrap
import threading
import token
import tokenize
import traceback
import urllib.parse
import warnings
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence, Sized
from copy import deepcopy
from itertools import chain, count
from pathlib import Path
from types import FunctionType
from typing import Any, Literal, NamedTuple, Self

from dateutil.relativedelta import relativedelta
from lxml import etree
from markupsafe import Markup, escape
from psycopg.errors import (
    DeadlockDetected,
    ReadOnlySqlTransaction,
    SerializationFailure,
    TransactionRollback,
)

from odoo import api, models, tools
from odoo.exceptions import UserError
from odoo.http import request
from odoo.libs.constants import SUPPORTED_DEBUGGER
from odoo.libs.lru import LRU
from odoo.modules import Manifest
from odoo.modules.registry import _REGISTRY_CACHES
from odoo.tools import OrderedSet, config, frozendict, json, safe_eval
from odoo.tools.image import FILETYPE_BASE64_MAGICWORD, image_data_uri
from odoo.tools.misc import file_open, file_path
from odoo.tools.profiler import ExecutionContext, QwebTracker
from odoo.tools.rendering_tools import QWebError, QWebErrorInfo
from odoo.tools.safe_eval import (
    _BLACKLIST,
    _BUILTINS,
    _EXPR_OPCODES,
    assert_valid_codeobj,
    to_opcodes,
)
from odoo.tools.translate import FORMAT_REGEX
from odoo.tools.urls import keep_query

_logger = logging.getLogger(__name__)


# Synthetic token type used by ``_compile_expr_tokens`` to splice an
# already-compiled sub-expression back into the token stream. A module constant
# rather than a monkeypatched ``token.QWEB`` attribute, to avoid polluting the
# process-global ``token`` namespace. Only the name is registered in
# ``token.tok_name`` so a debug ``repr`` of the token still reads "QWEB".
QWEB_TOKEN_TYPE = token.NT_OFFSET - 1
token.tok_name[QWEB_TOKEN_TYPE] = "QWEB"


# security safe eval opcodes for generated expression validation, used in `_compile_expr`
_SAFE_QWEB_OPCODES = (
    _EXPR_OPCODES.union(
        to_opcodes(
            [
                "MAKE_FUNCTION",
                "CALL_FUNCTION",
                "CALL_FUNCTION_KW",
                "CALL_FUNCTION_EX",
                "CALL_METHOD",
                "LOAD_METHOD",
                "GET_ITER",
                "FOR_ITER",
                "YIELD_VALUE",
                "JUMP_FORWARD",
                "JUMP_ABSOLUTE",
                "JUMP_BACKWARD",
                "JUMP_IF_FALSE_OR_POP",
                "JUMP_IF_TRUE_OR_POP",
                "POP_JUMP_IF_FALSE",
                "POP_JUMP_IF_TRUE",
                "LOAD_NAME",
                "LOAD_ATTR",
                "LOAD_FAST",
                "STORE_FAST",
                "UNPACK_SEQUENCE",
                "STORE_SUBSCR",
                "LOAD_GLOBAL",
                "EXTENDED_ARG",
                # Following opcodes were added in 3.11 https://docs.python.org/3/whatsnew/3.11.html#new-opcodes
                "RESUME",
                "CALL",
                "PRECALL",
                "PUSH_NULL",
                "KW_NAMES",
                "FORMAT_VALUE",
                "BUILD_STRING",
                "RETURN_GENERATOR",
                "SWAP",
                "POP_JUMP_FORWARD_IF_FALSE",
                "POP_JUMP_FORWARD_IF_TRUE",
                "POP_JUMP_BACKWARD_IF_FALSE",
                "POP_JUMP_BACKWARD_IF_TRUE",
                "POP_JUMP_FORWARD_IF_NONE",
                "POP_JUMP_FORWARD_IF_NOT_NONE",
                "POP_JUMP_BACKWARD_IF_NONE",
                "POP_JUMP_BACKWARD_IF_NOT_NONE",
                # 3.12 https://docs.python.org/3/whatsnew/3.12.html#new-opcodes
                "END_FOR",
                "LOAD_FAST_AND_CLEAR",
                "POP_JUMP_IF_NOT_NONE",
                "POP_JUMP_IF_NONE",
                "RERAISE",
                "CALL_INTRINSIC_1",
                "STORE_SLICE",
                # 3.13
                "CALL_KW",
                "LOAD_FAST_LOAD_FAST",
                "STORE_FAST_STORE_FAST",
                "STORE_FAST_LOAD_FAST",
                "CONVERT_VALUE",
                "FORMAT_SIMPLE",
                "FORMAT_WITH_SPEC",
                "SET_FUNCTION_ATTRIBUTE",
                # 3.14
                "LOAD_FAST_BORROW",  # optimized LOAD_FAST for borrowed references
                "POP_ITER",  # replaces END_FOR for iterator cleanup
                "LOAD_FAST_BORROW_LOAD_FAST_BORROW",  # compound load optimization
                "LOAD_COMMON_CONSTANT",  # loads common constants (None, NotImplemented, etc.)
            ]
        )
    )
    - _BLACKLIST
)


# eval to compile generated string python code into binary code, used in `_compile`
unsafe_eval = eval  # noqa: S307


VOID_ELEMENTS = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "keygen",
        "link",
        "menuitem",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)
# HTML elements on which a QWeb field/widget (``t-field``/``t-out`` with a
# widget) cannot render correctly, so their use is rejected at compile time.
FORBIDDEN_FIELD_TAGS = frozenset(
    [
        "table",
        "tbody",
        "thead",
        "tfoot",
        "tr",
        "td",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
    ]
)
# Terms allowed in addition to AVAILABLE_OBJECTS when compiling python expressions
ALLOWED_KEYWORD = frozenset(
    [
        "False",
        "None",
        "True",
        "and",
        "as",
        "elif",
        "else",
        "for",
        "if",
        "in",
        "is",
        "not",
        "or",
    ]
    + list(_BUILTINS)
)
RSTRIP_REGEXP = re.compile(r"\n[ \t]*$")
LSTRIP_REGEXP = re.compile(r"^[ \t]*\n")
FIRST_RSTRIP_REGEXP = re.compile(r"^(\n[ \t]*)+(\n[ \t])")
VARNAME_REGEXP = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Marker comment emitted before each compiled element (``_element_marker``) and
# parsed back by ``_get_error_info`` to map a generated-code line to its source
# node. The payload is a repr-encoded ``(path, xml)`` pair recovered with
# ``ast.literal_eval`` (see ``_scan_error_source``) — NOT split on a delimiter,
# since an ``xml`` fragment can itself contain the ``' , '`` separator. Emitter
# and parser MUST stay in sync.
ELEMENT_MARKER_REGEXP = re.compile(r"\s*# element: (.*)")
TO_VARNAME_REGEXP = re.compile(r"[^A-Za-z0-9_]+")
# Attribute name used outside the context of the QWeb.
SPECIAL_DIRECTIVES = {"t-translation", "t-ignore", "t-title"}
# Name of the variable to insert the content in t-call in the template.
# The slot will be replaced by the `t-call` tag content of the caller.
T_CALL_SLOT = "0"

# The generated ``code`` is executed wrapped in a one-line
# ``def generate_functions():`` preamble (see ``_generate_code_uncached``), so
# tracebacks report line numbers offset by that preamble relative to the stored
# code. ``_error_line_number`` subtracts this to realign. Update if the wrapper
# preamble ever grows (the error-surrounding tests pin the alignment).
GENERATED_CODE_PREAMBLE_LINES = 1

# Maximum depth of the explicit render stack in ``_render_iterall`` (t-call
# nesting). Exceeding it signals unbounded recursion (e.g. a template that
# t-calls itself) rather than a legitimately deep page, and aborts with a
# RecursionError instead of exhausting memory.
QWEB_MAX_RENDER_DEPTH = 50

ETREE_TEMPLATE_REF = count()

# Only allow a javascript scheme if it is followed by [ ][window.]history.back()
MALICIOUS_SCHEMES = re.compile(
    r"javascript:(?!( ?)((window\.)?)history\.back\(\)$)", re.IGNORECASE
).findall
# C0 control characters (incl. TAB, LF, CR, NUL) are stripped from a URL by the
# browser before the scheme resolves, so ``java&#9;script:`` collapses to
# ``javascript:`` and executes. Strip them before the MALICIOUS_SCHEMES match so
# those obfuscations are caught; stripping only adds detections (the cleaned form
# is matched, never the stored value), so legitimate URLs are unaffected.
URL_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")


def _id_or_xmlid(ref: str | int) -> str | int:
    try:
        return int(ref)
    except ValueError:
        return ref


def indent_code(code: str, level: int) -> str:
    """Indent the code to respect the python syntax."""
    return textwrap.indent(textwrap.dedent(code).strip(), " " * 4 * level)


def _group_caches_by_prefix(caches: Mapping[str, Any]) -> dict[str, list]:
    """Group cache objects by the prefix before the first dot in their name.

    Module-level (not a class-body loop) because a class-body ``for`` would leak
    the loop variables as class attributes and a nested comprehension can't see
    the class-level cache dict.
    """
    groups: dict[str, list] = {}
    for name, cache in caches.items():
        groups.setdefault(name.split(".")[0], []).append(cache)
    return groups


class QwebCallParameters(NamedTuple):
    context: dict[str, Any]
    view_ref: str | int
    method: str | None
    values: dict[str, Any] | None
    scope: bool | Literal["root"]
    directive: str
    path_xml: tuple[str | int, str, str] | None

    def __repr__(self) -> str:
        # cleaning context and values in order to have a consistent log when debugging.
        context = {k: v for k, v in self.context.items() if not k.startswith("_")}
        # ``values`` is None on the synthetic root frame (see ``_render_iterall``).
        qweb_root_values = (self.values or {}).get("__qweb_root_values") or {}
        values = self.values and {
            k: v
            for k, v in self.values.items()
            if k not in ("__qweb_root_values", "__qweb_attrs__")
            if v is not qweb_root_values.get(k)
        }
        return (
            f"<QwebCallParameters context={context!r} view_ref={self.view_ref!r}"
            f" method={self.method!r} values={values!r} scope={self.scope!r}"
            f" directive={self.directive!r} path_xml={self.path_xml!r}>"
        )


class QwebStackFrame(NamedTuple):
    params: QwebCallParameters | QwebContent
    irQweb: IrQweb
    iterator: Iterator[str | QwebCallParameters | QwebContent]
    values: dict[str, Any]
    options: dict[str, Any] | None

    def __repr__(self) -> str:
        return f"<QwebStackFrame {self.params!r}>"


class QwebContent:
    """QwebContent wraps a snippet to be used as a string value or a fragment.
    If the value is used with a string operation (from a qweb directive
    like `t-att-help="value % 1"`), the QwebContent loads the snippet.
    If the value is inserted in the document (`t-out="value"`), the snippet
    params bubble up to `_render_iterall`.
    """

    __irQweb: IrQweb
    html: str | None
    params__: (
        QwebCallParameters  # not available for the python expression inside the xml
    )

    def __init__(self, irQweb: IrQweb, params: QwebCallParameters) -> None:
        self.__irQweb = irQweb
        self.html = None
        self.params__ = params

    @property
    def irQweb(self) -> IrQweb | None:
        # A QwebContent that outlived its request (e.g. cached and reused while
        # serving a different database) would otherwise render through its
        # stale/foreign cursor. Refuse it when the current thread now serves
        # another database. (upstream odoo/odoo 07a333c8 + 49b312f5)
        irQweb = self.__irQweb
        thread_dbname = getattr(threading.current_thread(), "dbname", None)
        if thread_dbname and thread_dbname != irQweb.env.cr.dbname:
            return None
        return irQweb

    def __str__(self) -> str:
        if self.html is None:
            if self.irQweb is None:
                return ""
            params = self.params__
            self.html = "".join(
                self.irQweb._render_iterall(
                    params.view_ref,
                    params.method,
                    params.values,
                    params.directive,
                )
            )
        return self.html

    def __repr__(self) -> str:
        return f"<QwebContent {self.params__!r}>"

    def __len__(self) -> int:
        return len(str(self))

    def __html__(self) -> str:
        return self.__str__()

    def __contains__(self, key: str) -> bool:
        return key in Markup(self)

    def __getattr__(self, name: str) -> Any:
        return getattr(Markup(self), name)

    def __getitem__(self, key: int | slice) -> Any:
        return Markup(self)[key]

    def __add__(self, other: Any) -> Markup:
        return Markup(self).__add__(other)

    def __radd__(self, other: Any) -> Markup:
        return Markup(self).__radd__(other)

    def __mod__(self, other: Any) -> Markup:
        return Markup(self).__mod__(other)

    def __rmod__(self, other: Any) -> Markup:
        return Markup(self).__rmod__(other)


class QwebJSON(json.JSON):
    def dumps(self, *args: Any, **kwargs: Any) -> str:
        prev_default = kwargs.pop("default", lambda obj: obj)
        return super().dumps(
            *args,
            **kwargs,
            default=(
                lambda obj: prev_default(
                    str(obj) if isinstance(obj, QwebContent) else obj
                )
            ),
        )


qwebJSON = QwebJSON()


class IrQweb(models.AbstractModel):
    """Base QWeb rendering engine.

    Subclass ``ir.qweb.field`` as :samp:`ir.qweb.field.{widget}` to customize
    ``t-field`` rendering. For extensions that could clash with other subsystems,
    inherit ``ir.qweb`` into a local model rather than altering this one.
    """

    _name = "ir.qweb"
    _description = "Qweb"

    @api.model
    def _render(
        self,
        template: int | str | etree._Element,
        values: dict[str, Any] | None = None,
        **options: Any,
    ) -> Markup:
        """Render the template specified by the given name.

        :param template: etree, xml_id, template name (see _get_template)
            * Call the method ``load`` is not an etree.
        :param dict values: template values to be used for rendering
        :param options: used to compile the template
            Options will be add into the IrQweb.env.context for the rendering.

            * ``lang`` (str) used language to render the template
            * ``inherit_branding`` (bool) add the tag node branding
            * ``inherit_branding_auto`` (bool) add the branding on fields
            * ``minimal_qcontext``(bool) To use the minimum context and options
              from ``_prepare_environment``

        :return: the rendered template, markup-safe
        :rtype: markupsafe.Markup
        """
        # profiling code
        current_thread = threading.current_thread()
        execution_context_enabled = getattr(current_thread, "profiler_params", {}).get(
            "execution_context_qweb"
        )
        qweb_hooks = getattr(current_thread, "qweb_hooks", ())
        if execution_context_enabled or qweb_hooks:
            # To have the new compilation cached because the generated code will change.
            # Therefore 'profile' is a key to the cache.
            options["profile"] = True

        values = values.copy() if values else {}
        # The t-call content slot is keyed by the *integer* 0 at render time:
        # ``T_CALL_SLOT`` ("0") interpolated bare into the generated f-strings
        # becomes an int literal (``values.get(0, '')``). A caller must not
        # pre-occupy the slot, so strip both spellings — guarding only the str
        # form (the historical behaviour) silently let an int-0 value leak into
        # the slot.
        if T_CALL_SLOT in values or 0 in values:
            _logger.warning(
                "values[0] should be unset when call the _render method and only set into the template."
            )
            values.pop(T_CALL_SLOT, None)
            values.pop(0, None)

        irQweb = self.with_context(**options)._prepare_environment(values)
        # Render-local memo of `_compile` results, keyed by (view_ref, cache-key
        # signature). Avoids re-entering `_compile` on every `t-call`/content
        # frame (see `_render_iterall`). A caller rendering the same template
        # repeatedly (batch/mass rendering of an etree template, which is NOT
        # ormcached) may pass a persistent cache in context to compile once and
        # reuse it across calls; ``is None`` (not falsy) so an initially-empty
        # shared cache is reused in place rather than replaced. Absent the key,
        # each render gets its own fresh cache exactly as before.
        _compiled_cache = irQweb.env.context.get("__qweb_compiled_cache")
        irQweb = irQweb.with_context(
            # List of generated and/or used functions, used for optimal performance
            __qweb_loaded_functions={},
            __qweb_compiled_cache={} if _compiled_cache is None else _compiled_cache,
            # List of codes generated during compilation. It is mainly used for debugging and displaying error messages.
            __qweb_loaded_codes={},
            __qweb_loaded_options={},
            # Reference to the last node being compiled. It is mainly used for debugging and displaying error messages.
            _qweb_error_path_xml=[None, None, None],
        )

        safe_eval.check_values(values)

        root_values = values.copy()
        values["__qweb_root_values"] = root_values["__qweb_root_values"] = root_values

        iterator = irQweb._render_iterall(template, None, values)
        return Markup("".join(iterator))

    def _render_iterall(
        self,
        view_ref: int | str | etree._Element,
        method: str | None,
        values: dict[str, Any],
        directive: str = "render",
    ) -> Iterator[str]:
        """Drive the render stack, yielding output strings."""
        root_values = values["__qweb_root_values"]
        loaded_functions = self.env.context["__qweb_loaded_functions"]
        compiled_cache = self.env.context["__qweb_compiled_cache"]

        params = QwebCallParameters(
            context={},
            view_ref=view_ref,
            method=method,
            values=None,
            scope=False,
            directive=directive,
            path_xml=None,
        )
        stack = [QwebStackFrame(params, self, iter([params]), values, None)]

        try:
            while stack:
                if len(stack) > QWEB_MAX_RENDER_DEPTH:
                    msg = "Qweb template infinite recursion"
                    raise RecursionError(msg)

                frame = stack[-1]

                for item in frame.iterator:
                    # To debug the rendering step by step you can log the (len(stack) * '  ', repr(item))
                    if isinstance(item, str):
                        yield item
                        continue

                    # use QwebContent params or return already evaluated QwebContent
                    if is_content := isinstance(item, QwebContent):
                        if item.html is not None:
                            yield item.html
                            continue
                        params = item.params__

                    else:  # isinstance(item, QwebCallParameters)
                        params = item

                    values = frame.values
                    irQweb = frame.irQweb

                    if params.context:
                        irQweb = irQweb.with_context(**params.context)

                    # A content (QwebContent) frame carries the def_name of a
                    # function registered in `loaded_functions` by an earlier
                    # compilation; look it up there directly. This MUST stay:
                    # etree templates recompile with fresh, non-deterministic
                    # def_names (ETREE_TEMPLATE_REF) and are not ormcached, so a
                    # re-`_compile` below would NOT reproduce that name.
                    render_template = loaded_functions.get(params.method)

                    # Fetch the compiled function and template options, memoized
                    # per render. Re-entering `_compile` on every frame is
                    # ormcached for DB templates but still costs a cache-key
                    # computation per frame (and t-call defeated the
                    # `loaded_functions` fast-path entirely). Key on the template
                    # ref AND the compile cache-key signature: a `t-call` +
                    # `t-lang` legitimately recompiles the same ref under a
                    # different lang (a cache key), so a ref-only key is wrong.
                    compile_key = (
                        params.view_ref,
                        irQweb._template_cache_signature(),
                    )
                    compiled = compiled_cache.get(compile_key)
                    if compiled is None:
                        compiled = irQweb._compile(params.view_ref)
                        compiled_cache[compile_key] = compiled
                        loaded_functions.update(compiled[0])
                    template_functions, def_name, options = compiled
                    if not render_template:
                        render_template = template_functions[params.method or def_name]

                    if params.scope:
                        if params.scope == "root":
                            values = root_values
                        values = values.copy()

                    if params.values:
                        values.update(params.values)

                    iterator = iter([])
                    try:
                        iterator = render_template(irQweb, values)
                    finally:
                        if is_content and self.env.context["_qweb_error_path_xml"][1]:
                            # add a stack frame to log a complete error with the path when compile the template
                            logParams = QwebCallParameters(
                                *(
                                    params[0:-1]
                                    + (tuple(self.env.context["_qweb_error_path_xml"]),)
                                )
                            )
                            stack.append(
                                QwebStackFrame(logParams, irQweb, [], values, options)
                            )
                        stack.append(
                            QwebStackFrame(params, irQweb, iterator, values, options)
                        )
                    break

                else:
                    stack.pop()

        except (
            TransactionRollback,
            SerializationFailure,
            DeadlockDetected,
            ReadOnlySqlTransaction,
        ):
            raise

        except Exception as error:
            # Never returns normally: converts to QWebError or annotates and re-raises.
            self._wrap_render_error(error, stack, frame, view_ref)

    def _wrap_render_error(
        self,
        error: Exception,
        stack: list[QwebStackFrame],
        frame: QwebStackFrame,
        view_ref: int | str | etree._Element,
    ) -> None:
        """Convert a render-time exception into a ``QWebError`` (or annotate an
        existing one) and re-raise. Never returns normally.
        """
        qweb_error_info = self._get_error_info(error, stack, stack[-1])
        if qweb_error_info.template is None and qweb_error_info.ref is None:
            qweb_error_info.ref = view_ref

        if hasattr(error, "qweb"):
            if qweb_error_info.source:
                error.qweb.source = qweb_error_info.source + error.qweb.source
            if not error.qweb.ref and frame.params.view_ref:
                error.qweb.ref = frame.params.view_ref
            qweb_error_info = error.qweb
        elif not isinstance(error, UserError):
            # Not an odoo exception: if it originated inside IrQweb (models or
            # compiled code) convert it into a QWebError.
            if self._error_raised_in_qweb(error):
                raise QWebError(qweb_error_info) from error

        error.qweb = qweb_error_info
        # Re-raise the original exception (annotated with ``.qweb``). ``raise
        # error`` rather than a bare ``raise`` because this runs in a helper,
        # not directly in the ``except`` block.
        raise error

    def _error_raised_in_qweb(self, error: Exception) -> bool:
        """Whether ``error``'s traceback shows it originated inside IrQweb (this
        module, or a compiled template method on this model) rather than in
        unrelated addon code.

        Walks the traceback from the innermost frame outward: an IrQweb frame
        means yes, an addons-path frame reached first means no.
        """
        trace = error.__traceback__
        tb_frames = [trace.tb_frame]
        while trace.tb_next is not None:
            trace = trace.tb_next
            tb_frames.append(trace.tb_frame)
        for tb_frame in tb_frames[::-1]:
            if tb_frame.f_globals.get("__name__") == __name__ or (
                isinstance(tb_frame.f_locals.get("self"), models.AbstractModel)
                and tb_frame.f_locals["self"]._name == self._name
            ):
                return True
            if any(
                path in tb_frame.f_code.co_filename
                for path in tools.config["addons_path"]
            ):
                return False
        return False

    def _get_error_info(
        self,
        error: Exception,
        stack: list[QwebStackFrame],
        frame: QwebStackFrame,
    ) -> QWebErrorInfo:
        """Build the ``QWebErrorInfo`` (template ref, source node, and dev-mode
        code snippet) for an exception raised while rendering.

        The work is split into: choosing the frame to blame
        (``_resolve_error_frame``), finding the failing generated-code line
        (``_error_line_number``), mapping that line back to a source node via
        the ``# element:`` markers (``_scan_error_source``), and — in dev mode —
        framing the offending code (``_error_surrounding``).
        """
        no_id_ref = "etree._Element"

        ref, ref_name, code, path, html = self._resolve_error_frame(
            error, stack, frame, no_id_ref
        )

        line_nb = self._error_line_number(ref, no_id_ref)

        source = [info.params.path_xml for info in stack if info.params.path_xml]
        code_lines = (code or "").split("\n")

        path, html = self._scan_error_source(
            code_lines, line_nb, ref, source, path, html
        )

        if path:
            source.append((ref, path, html))

        surrounding = None
        if self.env.context.get("dev_mode") and line_nb:
            surrounding = self._error_surrounding(code_lines, line_nb, html)

        return QWebErrorInfo(
            f"{error.__class__.__name__}: {error}",
            ref if ref_name is None else ref_name,
            ref,
            path,
            html,
            source,
            surrounding,
        )

    def _resolve_error_frame(
        self,
        error: Exception,
        stack: list[QwebStackFrame],
        frame: QwebStackFrame,
        no_id_ref: str,
    ) -> tuple[Any, str | None, str | None, str | None, str | None]:
        """Choose the template frame to blame for ``error`` and return
        ``(ref, ref_name, code, path, html)``.

        Normally the failing (current) frame is used; but a nested failure
        (e.g. inside a ``t-call``) whose own code isn't loaded falls back to the
        calling frame so the erroneous node can still be shown.
        """
        loaded_codes = self.env.context["__qweb_loaded_codes"]
        path = html = None
        # The compilation may have failed before the options were loaded, hence
        # the ``or {}`` fallbacks below.
        if (
            frame.params.view_ref in loaded_codes
            and not isinstance(error, RecursionError)
        ) or len(stack) <= 1:
            options = frame.options or {}
            if "ref" not in options:
                options = (
                    self.env.context["__qweb_loaded_options"].get(frame.params.view_ref)
                    or {}
                )
            # The template can have a null reference, e.g. for a provided etree.
            ref = options.get("ref") or frame.params.view_ref
            ref_name = options.get("ref_name") or None
            code = loaded_codes.get(frame.params.view_ref) or loaded_codes.get(
                no_id_ref
            )
            if ref == self.env.context["_qweb_error_path_xml"][0]:
                path = self.env.context["_qweb_error_path_xml"][1]
                html = self.env.context["_qweb_error_path_xml"][2]
        else:
            # get the previous caller (like t-call) to display erroneous xml node.
            options = stack[-2].options or {}
            ref = options.get("ref")
            ref_name = options.get("ref_name")
            code = loaded_codes.get(ref) or loaded_codes.get(no_id_ref)
            if frame.params.path_xml:
                path = frame.params.path_xml[1]
                html = frame.params.path_xml[2]
        return ref, ref_name, code, path, html

    def _error_line_number(self, ref: Any, no_id_ref: str) -> int:
        """Line number of the failing statement inside the *stored* generated
        code, parsed from the active traceback (0 when it cannot be located).

        The traceback reports line numbers in the executed, wrapped code; the
        stored code (indexed by the callers) omits the wrapper preamble, so the
        parsed number is realigned by ``GENERATED_CODE_PREAMBLE_LINES``.
        """
        source_file_ref = None if ref == no_id_ref else ref
        trace = traceback.format_exc()
        for error_line in reversed(trace.split("\n")):
            if f'File "<{source_file_ref}>"' in error_line or (
                ref is None and 'File "<' in error_line
            ):
                line_function = error_line.split(", line ")[1]
                wrapped_line = int(line_function.split(",")[0])
                return wrapped_line - GENERATED_CODE_PREAMBLE_LINES
        return 0

    def _scan_error_source(
        self,
        code_lines: list[str],
        line_nb: int,
        ref: Any,
        source: list[tuple[Any, str, str]],
        path: str | None,
        html: str | None,
    ) -> tuple[str | None, str | None]:
        """Walk the generated code upward from the error line, reading the
        ``# element:`` markers to recover the failing source node (returned as
        the resolved ``(path, html)``) and its enclosing nodes (appended to
        ``source`` in place)."""
        found = False
        for code_line in reversed(code_lines[:line_nb]):
            if code_line.startswith("def "):
                break
            match = ELEMENT_MARKER_REGEXP.match(code_line)
            if not match:
                if found:
                    break
                continue
            # The marker payload is ``{path!r} , {xml!r}``; recover it with
            # ``literal_eval`` so a ``' , '`` inside the xml (or the path) does
            # not truncate either field. See ELEMENT_MARKER_REGEXP.
            marker_path, marker_xml = ast.literal_eval(match[1])
            if found:
                info = (ref, marker_path, marker_xml)
                if info not in source:
                    source.append(info)
            else:
                found = True
                path = marker_path
                html = marker_xml
        return path, html

    def _error_surrounding(
        self, code_lines: list[str], line_nb: int, html: str | None
    ) -> str:
        """Build the dev-mode snippet framing the error line with its surrounding
        context.

        ``line_nb`` is already realigned to the stored code by
        ``_error_line_number``, so ``code_lines[line_nb - 1]`` is the culprit for
        every directive (no per-directive nudging needed)."""
        previous_lines = "\n".join(code_lines[max(line_nb - 25, 0) : line_nb - 1])
        line = code_lines[line_nb - 1]
        next_lines = "\n".join(code_lines[line_nb : line_nb + 5])
        indent = re.search(r"^(\s*)", line).group(0)
        return textwrap.indent(
            textwrap.dedent(
                f"{previous_lines}\n"
                f"{indent}########### Line triggering the error ############\n{line}\n"
                f"{indent}##################################################\n{next_lines}"
            ),
            " " * 8,
        )

    # assume cache will be invalidated by third party on write to ir.ui.view
    def _get_template_cache_keys(self) -> list[str]:
        """Return the list of context keys to use for caching ``_compile``."""
        return [
            "lang",
            "inherit_branding",
            "inherit_branding_auto",
            "edit_translations",
            "profile",
        ]

    def _template_cache_signature(self) -> tuple:
        """Context-derived half of ``_compile``'s cache key (the template ref is
        the other half). Falsy context values collapse to ``False`` so contexts
        that differ only in the spelling of "empty" share one compiled function.

        Single source of truth: the ``@ormcache`` on ``_generate_code_cached``
        and the render-local ``compiled_cache`` in ``_render_iterall`` MUST both
        key on this exact signature, or the memo and the ormcache disagree.
        Deliberately NOT the ``options`` dict from ``_generate_code`` (which keeps
        e.g. ``lang=''`` distinct from ``False``); that dict is for logs, not
        cache identity.
        """
        context = self.env.context
        return tuple(context.get(k) or False for k in self._get_template_cache_keys())

    def _get_template_info(self, template: int | str) -> dict[str, Any]:
        return self.env["ir.ui.view"]._get_cached_template_info(template)

    def _compile(
        self, template: int | str | etree._Element
    ) -> tuple[dict[str, Any], str, frozendict]:
        if isinstance(template, str) and template.endswith(".xml"):
            template_functions, def_name, options = self._generate_code_file_cached(
                template
            )
        elif isinstance(template, etree._Element) or not (
            ref := self._get_template_info(template)["id"]
        ):
            # etree elements, and identifiers that resolve to no view (falsy
            # ref): compile uncached — the latter so the generated
            # ``not_found_template`` reports the requested identifier.
            template_functions, def_name, options = self._generate_code_uncached(
                template
            )
        else:
            template_functions, def_name, options = self._generate_code_cached(ref)

        render_template = template_functions[def_name]
        if (
            options.get("profile")
            and render_template.__name__ != "profiled_method_compile"
        ):
            ref = options.get("ref")
            ref_xml = str(val) if (val := options.get("ref_xml")) else None

            def wrap(function: FunctionType) -> FunctionType:
                def profiled_method_compile(self: Any, values: dict[str, Any]) -> Any:
                    qweb_tracker = QwebTracker(ref, ref_xml, self.env.cr)
                    self = self.with_context(qweb_tracker=qweb_tracker)
                    if qweb_tracker.execution_context_enabled:
                        with ExecutionContext(template=ref):
                            return function(self, values)
                    return function(self, values)

                return profiled_method_compile

            # Wrap into a NEW mapping: ``template_functions`` may be the dict
            # returned by the ormcached ``_generate_code_cached`` and shared
            # across concurrent renders. Mutating it in place was a
            # check-then-act race (two renders passing the ``__name__`` guard
            # simultaneously double-wrapped the functions) and leaked the
            # profiling wrappers into the cache for every later caller.
            template_functions = {
                key: wrap(function) if isinstance(function, FunctionType) else function
                for key, function in template_functions.items()
            }

        return (template_functions, def_name, options)

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "ref",
            "self._template_cache_signature()",
            cache="templates",
        ),
    )
    def _generate_code_cached(self, ref: int) -> tuple[dict[str, Any], str, frozendict]:
        return self._generate_code_uncached(ref)

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "path",
            "self._template_cache_signature()",
            cache="templates",
        ),
    )
    def _generate_code_file_cached(
        self, path: str
    ) -> tuple[dict[str, Any], str, frozendict]:
        """Load, parse and compile a ``module/templates/*.xml`` file template.

        Cached like ``_generate_code_cached`` (and likewise disabled in
        ``xml`` dev mode): file templates are rendered in loops (e.g. one
        render per record in a report batch), and without this cache every
        render re-read the file, re-parsed it and re-ran the whole
        codegen + ``unsafe_eval`` pipeline.
        """
        module = Path(path).parts[0]
        # display_warning=False: the ValueError below is the error report.
        manifest = Manifest.for_addon(module, display_warning=False)
        if manifest is None:
            msg = (
                f"Cannot load template file {path!r}: "
                f"{module!r} is not a known Odoo module"
            )
            raise ValueError(msg)
        if "templates" not in Path(file_path(path)).relative_to(manifest.path).parts:
            msg = (
                f"The templates file {path!r} must be under a subfolder "
                "'templates' of a module"
            )
            raise ValueError(msg)
        with file_open(path, "rb", filter_ext=(".xml",)) as file:
            element = etree.fromstring(memoryview(file.read()))
        return self._generate_code_uncached(element)

    def _generate_code_uncached(
        self, template: int | str | etree._Element
    ) -> tuple[dict[str, Any], str, frozendict]:
        ref = (
            self._get_template_info(template)["id"]
            if isinstance(template, (int, str))
            else None
        )

        code, options, def_name = self._generate_code(template)

        if code is None:
            Error, message, stack = options["error"]

            def not_found_template(self: Any, values: dict[str, Any]) -> str:
                if tools.config["dev_mode"]:
                    _logger.info(stack)
                if self.env.context.get("raise_if_not_found", True):
                    raise Error(message)
                _logger.warning("Cannot load template %s: %s", template, message)
                return ""

            return (
                {"not_found_template": not_found_template},
                "not_found_template",
                frozendict(options),
            )

        # The single ``def generate_functions():`` preamble line shifts every
        # subsequent line of ``code`` by ``GENERATED_CODE_PREAMBLE_LINES`` in the
        # compiled/traceback coordinates; ``_error_line_number`` subtracts it to
        # map back onto the stored ``code``. Keep the two in sync.
        wrap_code = "\n".join(
            [
                "def generate_functions():",
                indent_code(code, 1),
                f"    code = {code!r}",
                "    return template_functions",
            ]
        )
        compiled = compile(wrap_code, f"<{ref}>", "exec")
        globals_dict = self._prepare_globals()
        globals_dict["__builtins__"] = (
            globals_dict  # So that unknown/unsafe builtins are never added.
        )
        unsafe_eval(compiled, globals_dict)
        return (
            globals_dict["generate_functions"](),
            def_name,
            frozendict(options),
        )

    def _generate_code(
        self, template: int | str | etree._Element
    ) -> tuple[str | None, dict[str, Any], str]:
        """Compile the given template into a rendering function (generator)::

            render_template(qweb, values)

        Called by :meth:`_generate_code_uncached` as part of the ``_compile``
        pipeline.

        An ``options`` dictionary is created and attached to the function.
        It contains rendering options that are part of the cache key in
        addition to template references.

        where ``qweb`` is a QWeb instance and ``values`` are the values to
        render.

        :returns: tuple containing code, options and main method name
        """
        if not isinstance(template, (int, str, etree._Element)):
            template = str(template)
        # ``compile_context`` carries the cache-key elements plus template
        # references and codegen scratch, used only while compiling. It starts as
        # a copy of ``self.env.context`` and is threaded by reference through
        # every ``_compile_*`` method. The QWeb-specific keys written below and
        # their owners:
        #   - "ref"/"ref_name"/"ref_xml": template identity (also read by
        #     html_editor's ir.qweb override).
        #   - "template": the identifier passed to ``_compile``.
        #   - "root": the etree root, for ``getpath`` in error markers.
        #   - "nsmap": inherited namespaces (see ``_new_namespaces``).
        #   - "make_name": unique-name generator for nested def_names.
        #   - "template_functions": {def_name: code_lines} accumulator.
        #   - "_text_concat": pending output chunks (see ``_append_text``).
        #   - "iter_directives": remaining directives for the current node.
        #   - "_qweb_error_path_xml": [ref, path, xml] scratch for error markers.
        #   - flags read via ``.get``: "profile", "dev_mode",
        #     "preserve_comments", "edit_translations", and — for the mail
        #     override — "raise_on_forbidden_code_for_model".
        compile_context = self.env.context.copy()

        try:
            element, document, ref = self._get_template(template)
        except (ValueError, UserError) as e:
            # return the error information if the template is not found or fail
            options = {
                k: compile_context.get(k, False)
                for k in self._get_template_cache_keys()
            }
            message = str(e)
            if hasattr(e, "context") and e.context.get("view"):
                message = f"{message} (view: {e.context['view'].key})"
            options["error"] = (e.__class__, message, traceback.format_exc())
            return (None, options, "not_found_template")

        compile_context.pop("raise_if_not_found", None)

        ref_name = element.attrib.pop("t-name", None)
        if isinstance(ref, int) or (isinstance(template, str) and "<" not in template):
            ref_name = self._get_template_info(ref)["key"] or ref_name

        # reference to get xml and etree (usually the template ID)
        compile_context["ref"] = ref
        # reference name or key to get xml and etree (usually the template XML ID)
        compile_context["ref_name"] = ref_name
        # str xml of the reference template used for compilation. Useful for debugging, dev mode and profiling.
        compile_context["ref_xml"] = str(document) if document else None
        # Identifier used to call `_compile`
        compile_context["template"] = template
        # Root of the etree which will be processed during compilation.
        compile_context["root"] = element.getroottree()
        # Reference to the last node being compiled. It is mainly used for debugging and displaying error messages.
        compile_context["_qweb_error_path_xml"] = compile_context.get(
            "_qweb_error_path_xml", [None, None, None]
        )

        compile_context["nsmap"] = {
            ns_prefix: str(ns_definition)
            for ns_prefix, ns_definition in compile_context.get("nsmap", {}).items()
        }

        # The options dictionary includes cache key elements and template
        # references. It will be attached to the generated function. This
        # dictionary is only there for logs, performance or test information.
        # The values of these `options` cannot be changed and must always be
        # identical in `context` and `self.env.context`.
        options = {
            key: compile_context.get(key, False)
            for key in self._get_template_cache_keys() + ["ref", "ref_name"]
        }

        # generate code
        ref_name = compile_context["ref_name"] or ""
        if isinstance(template, etree._Element):
            def_name = TO_VARNAME_REGEXP.sub(
                r"_", f"template_etree_{next(ETREE_TEMPLATE_REF)}"
            )
        else:
            def_name = TO_VARNAME_REGEXP.sub(
                r"_",
                f"template_{ref_name if '<' not in ref_name else ''}_{ref}",
            )

        name_gen = count()
        compile_context["make_name"] = lambda prefix: (
            f"{def_name}_{prefix}_{next(name_gen)}"
        )

        if element.text:
            element.text = FIRST_RSTRIP_REGEXP.sub(r"\2", element.text)

        compile_context["template_functions"] = {}

        compile_context["_text_concat"] = []
        self._append_text(
            "", compile_context
        )  # To ensure the template function is a generator and doesn't become a regular function
        compile_context["template_functions"][f"{def_name}_content"] = (
            [f"def {def_name}_content(self, values):"]
            + self._compile_node(element, compile_context, 2)
            + self._flush_text(compile_context, 2, rstrip=True)
        )

        compile_context["template_functions"][def_name] = [
            indent_code(
                f"""
            def {def_name}(self, values):
                if 'xmlid' not in values:
                    values['xmlid'] = {options["ref_name"]!r}
                    values['viewid'] = {options["ref"]!r}
                self.env.context['__qweb_loaded_functions'].update(template_functions)
                self.env.context['__qweb_loaded_options'][{options["ref"]!r}] = self.env.context['__qweb_loaded_options'][{options["ref_name"]!r}] = template_options
                self.env.context['__qweb_loaded_codes'][{options["ref"]!r}] = self.env.context['__qweb_loaded_codes'][{options["ref_name"]!r}] = code
                yield from {def_name}_content(self, values)
                """,
                0,
            )
        ]

        code_lines = []
        code_lines.extend(
            (
                f"template_options = {pprint.pformat(options, indent=4)}",
                "code = None",
                "template_functions = {}",
            )
        )

        for lines in compile_context["template_functions"].values():
            code_lines.extend(lines)

        code_lines.extend(
            f"template_functions[{name!r}] = {name}"
            for name in compile_context["template_functions"]
        )

        code = "\n".join(code_lines)

        if options.get("profile"):
            options["ref_xml"] = compile_context["ref_xml"]

        return (code, options, def_name)

    # read and load input template

    def _get_template(
        self, template: int | str | etree._Element
    ) -> tuple[etree._Element, str, str | int]:
        """Retrieve the given template, and return it as a tuple ``(etree,
        xml, ref)``, where ``element`` is an etree, ``document`` is the
        string document that contains ``element``, and ``ref`` is the unique
        reference of the template (id, t-name or template).

        :param template: template identifier or etree
        """
        if template in (False, None, ""):
            raise ValueError("template is required")

        # template is an xml etree already
        if isinstance(template, etree._Element):
            document = etree.tostring(template, encoding="unicode")
            # Compilation is destructive — each directive pops the attributes it
            # consumes (see _compile_node / _compile_directives) — so never
            # compile the caller's own element. A reused etree (rendered more
            # than once, or kept by the caller) would otherwise be stripped
            # after the first render and silently produce corrupted output.
            element = deepcopy(template)

            # <templates>
            #   <template t-name=... /> <!-- return ONLY this element -->
            #   <template t-name=... />
            # </templates>
            for node in element.iter():
                ref = node.get("t-name")
                if ref:
                    return (node, document, _id_or_xmlid(ref))

            return (element, document, "etree._Element")

        # template is xml as string
        if isinstance(template, str) and "<" in template:
            msg = "Inline templates must be passed as `etree` documents"
            raise ValueError(msg)

        # template is (id or ref) to a database stored template
        id_or_xmlid = _id_or_xmlid(
            template
        )  # e.g. <t t-call="33"/> or <t t-call="web.layout"/>
        value = self._preload_trees([id_or_xmlid]).get(id_or_xmlid)
        if value.get("error"):
            raise value["error"]

        # ``value["tree"]`` is cached for the whole transaction (see
        # ``_preload_trees``). Compilation is destructive (each directive pops the
        # attributes it consumes), so it MUST run on a private copy; otherwise a
        # recompile triggered by a mid-transaction eviction of the bounded
        # ``templates`` ormcache reads an already-stripped tree and silently
        # renders corrupted output.
        value_tree = deepcopy(value["tree"])
        # return etree, document and ref
        return (value_tree, value["template"], value["ref"])

    @api.model
    def _get_preload_attribute_xmlids(self) -> list[str]:
        return ["t-call"]

    def _preload_trees(
        self, refs: Sequence[int | str]
    ) -> dict[int | str, dict[str, Any]]:
        """Preload all tree and subtree (from t-call and other '_get_preload_attribute_xmlids' values).

        Returns::

            {
                id or xmlId / key: {
                    "xmlid": str | None,
                    "ref": int | None,
                    "tree": etree | None,
                    "template": str | None,
                    "error": None | MissingError,
                }
            }
        """
        compile_batch = self.env["ir.ui.view"]._preload_views(refs)

        refs = list(map(_id_or_xmlid, refs))
        missing_refs = {
            ref: compile_batch[ref]
            for ref in refs
            if "template" not in compile_batch[ref] and not compile_batch[ref]["error"]
        }
        if not missing_refs:
            return compile_batch

        views = (
            self.env["ir.ui.view"]
            .sudo()
            .union(*[data["view"] for data in missing_refs.values()])
        )

        trees = views._get_view_etrees()

        # add in cache
        # ``union`` dedupes: one batch may reference the same view under two
        # spellings (e.g. ``t-call="1234"`` and ``t-call="web.layout"``), so
        # ``views``/``trees`` can be shorter than ``missing_refs``. Resolve
        # each ref through a per-view map instead of zipping refs with views
        # (a strict zip raised ValueError on such batches).
        data_by_view_id = {
            view.id: {
                "tree": tree,
                "template": etree.tostring(tree, encoding="unicode"),
            }
            for view, tree in zip(views, trees, strict=True)
        }
        for ref, ref_data in missing_refs.items():
            data = data_by_view_id[ref_data["view"].id]
            compile_batch[ref_data["view"].id].update(data)
            compile_batch[ref].update(data)

        # preload sub template
        ref_names = self._get_preload_attribute_xmlids()
        sub_refs = OrderedSet()
        for view, tree in zip(views, trees, strict=True):
            for ref_name in ref_names:
                for el in tree.xpath(f"//*[@{ref_name}]"):
                    if any(
                        att.startswith("t-options-") or att in {"t-options", "t-lang"}
                        for att in el.attrib
                    ):
                        continue
                    sub_ref = el.get(ref_name)
                    if not sub_ref:
                        raise ValueError(
                            f"template is required: empty {ref_name!r} value "
                            f"in template {view.key or view.id!r}"
                        )
                    if "{" not in sub_ref and "<" not in sub_ref and "/" not in sub_ref:
                        sub_refs.add(sub_ref)
        if sub_refs:
            self._preload_trees(list(sub_refs))

        # ``missing_refs`` keys come from ``compile_batch`` by construction
        # (and nothing above deletes entries), so every ref is resolved here;
        # unknown refs already carry an ``error`` entry from ``_preload_views``.
        assert all(ref in compile_batch for ref in missing_refs), (
            "_preload_views must return an entry for every requested ref"
        )

        return compile_batch

    # values for running time

    def _get_converted_image_data_uri(self, base64_source: str | bytes) -> str:
        if self.env.context.get("webp_as_jpg"):
            # FILETYPE_BASE64_MAGICWORD is keyed by *bytes*; a str source
            # must be encoded before the lookup, otherwise it silently falls
            # back to "png" and the WebP → JPEG substitution below is skipped
            # (WeasyPrint then fails on the WebP data).
            magicword = (
                base64_source[:1].encode()
                if isinstance(base64_source, str)
                else base64_source[:1]
            )
            mimetype = FILETYPE_BASE64_MAGICWORD.get(magicword, "png")
            if "webp" in mimetype:
                # Convert WebP to JPEG for PDF rendering (WeasyPrint).
                bin_source = base64.b64decode(base64_source)
                Attachment = self.env["ir.attachment"]
                checksum = Attachment._content_checksum(bin_source)
                # The same image is typically resolved many times per report
                # batch (e.g. a logo repeated on every record); memoize the
                # checksum → converted-datas lookup for the transaction.
                converted_cache = self.env.cr.cache.setdefault(
                    "_webp_as_jpg_datas_", {}
                )
                if checksum not in converted_cache:
                    # Single query: the origin lookup (same checksum) runs as
                    # a subselect of the converted-copy search.
                    origins_query = Attachment.sudo()._search(
                        [
                            [
                                "id",
                                "!=",
                                False,
                            ],  # No implicit condition on res_field.
                            ["checksum", "=", checksum],
                        ]
                    )
                    converted = Attachment.sudo().search(
                        [
                            [
                                "id",
                                "!=",
                                False,
                            ],  # No implicit condition on res_field.
                            ["res_model", "=", "ir.attachment"],
                            ["res_id", "in", origins_query],
                            ["mimetype", "=", "image/jpeg"],
                        ],
                        limit=1,
                    )
                    converted_cache[checksum] = converted.datas if converted else None
                if converted_cache[checksum]:
                    base64_source = converted_cache[checksum]
        return image_data_uri(base64_source)

    def _prepare_environment(self, values: dict[str, Any]) -> Self:
        """Prepare the values and context sent to the compiled and evaluated
        function.

        :param values: template values to be used for rendering
        :return: self (with new context)
        """
        debug = (request and request.session.debug) or ""
        values.update(
            true=True,
            false=False,
        )
        if not self.env.context.get("minimal_qcontext"):
            values.setdefault("debug", debug)
            values.setdefault("user_id", self.env.user.with_env(self.env))
            values.setdefault("res_company", self.env.company.sudo())
            values.update(
                request=request,  # might be unbound if we're not in an httprequest context
                test_mode_enabled=config["test_enable"],
                json=qwebJSON,
                quote_plus=urllib.parse.quote_plus,
                time=safe_eval.time,
                datetime=safe_eval.datetime,
                relativedelta=relativedelta,
                image_data_uri=self._get_converted_image_data_uri,
                # specific 'math' functions to ease rounding in templates and lessen controller marshalling
                floor=math.floor,
                ceil=math.ceil,
                env=self.env,
                lang=self.env.context.get("lang"),
                keep_query=keep_query,
            )

        context = {"dev_mode": "qweb" in tools.config["dev_mode"]}
        return self.with_context(**context)

    def _prepare_globals(self) -> dict[str, Any]:
        """Prepare the global namespace used to eval the qweb generated code."""
        return {
            "__name__": __name__,
            "Sized": Sized,
            "Mapping": Mapping,
            "Markup": Markup,
            "escape": escape,
            "VOID_ELEMENTS": VOID_ELEMENTS,
            "QwebCallParameters": QwebCallParameters,
            "QwebContent": QwebContent,
            "ValueError": ValueError,
            **_BUILTINS,
        }

    # helpers for compilation

    def _append_text(
        self, text: str | bytes | None, compile_context: dict[str, Any]
    ) -> None:
        """Queue ``text`` (coerced to str) for the next ``_flush_text``, so
        multiple parts are emitted in a single yield."""
        compile_context["_text_concat"].append(self._compile_to_str(text))

    def _strip_pending_trailing_ws(self, compile_context: dict[str, Any]) -> None:
        """If the last not-yet-flushed text chunk is pure whitespace, drop its
        trailing spaces/tabs.

        Used when a comment or processing instruction is removed from the DOM:
        the indentation that preceded it would otherwise linger as invisible
        trailing whitespace on an now-blank line.
        """
        text_concat = compile_context["_text_concat"]
        if text_concat and text_concat[-1].isspace():
            text_concat[-1] = text_concat[-1].rstrip(" \t")

    def _rstrip_text(self, compile_context: dict[str, Any]) -> str:
        """Right-strip the pending text and return the stripped-off whitespace."""
        text_concat = compile_context["_text_concat"]
        if not text_concat:
            return ""

        result = RSTRIP_REGEXP.search(text_concat[-1])
        strip = result.group(0) if result else ""
        text_concat[-1] = RSTRIP_REGEXP.sub("", text_concat[-1])

        return strip

    def _flush_text(
        self, compile_context: dict[str, Any], level: int, rstrip: bool = False
    ) -> list[str]:
        """Concatenate all the textual chunks added by ``_append_text`` into a
        single ``yield`` line. Return an empty list if there is no text to flush.

        :param bool rstrip: if set, right-strip the concatenated text.
        :rtype: list[str]
        """
        text_concat = compile_context["_text_concat"]
        if not text_concat:
            return []
        if rstrip:
            self._rstrip_text(compile_context)
        text = "".join(text_concat)
        text_concat.clear()
        return [f"{'    ' * level}yield {text!r}"]

    def _is_static_node(
        self, el: etree._Element, compile_context: dict[str, Any]
    ) -> bool:
        """Whether ``el`` is purely static: no ``t-*`` attribute needing dynamic
        rendering.
        """
        return (
            el.tag != "t"
            and "groups" not in el.attrib
            and not any(
                att.startswith("t-") and att not in ("t-tag-open", "t-inner-content")
                for att in el.attrib
            )
        )

    def _new_namespaces(
        self, el: etree._Element, compile_context: dict[str, Any]
    ) -> set[tuple[str | None, str]]:
        """Return the ``(prefix, uri)`` namespaces declared on ``el`` that are
        not already inherited from ``compile_context['nsmap']``.

        lxml inlines the full nsmap onto every element, so a plain
        ``el.nsmap`` cannot tell apart newly-introduced namespaces from
        inherited ones; the set difference recovers only the new ones.
        """
        return set(el.nsmap.items()) - set(compile_context["nsmap"].items())

    def _ns_prefix_map(
        self, el: etree._Element, compile_context: dict[str, Any]
    ) -> dict[str, str | None]:
        """Return a ``uri -> prefix`` map used to restore the namespace
        prefixes that lxml inlined into qualified attribute names."""
        return {
            uri: prefix
            for prefix, uri in chain(compile_context["nsmap"].items(), el.nsmap.items())
        }

    def _element_marker(self, path: str | None, xml: str | None) -> str:
        """Return the marker comment emitted before an element's compiled code.

        Parsed back by ``_get_error_info`` (via ``ELEMENT_MARKER_REGEXP``) to
        recover the source node for an error line — the format is shared, so
        both live next to that regexp.
        """
        return f"# element: {path!r} , {xml!r}"

    # compile python expression and format string

    def _compile_format(self, expr: str) -> str:
        """Parse the format string and compile it to a single python
        ``%``-format expression, which is faster than concatenating the
        strings and values.
        """
        # <t t-setf-name="Hello #{world} %s !"/>
        # =>
        # values['name'] = 'Hello %s %%s !' % (values['world'],)
        values = [
            f"self._compile_to_str({self._compile_expr(m.group(1) or m.group(2))})"
            for m in FORMAT_REGEX.finditer(expr)
        ]
        if not values:
            # no placeholder: the '%'-escape below is never undone, so a literal
            # '%' (e.g. "Save 50%") would leak as "%%" into the output
            return repr(expr)
        # ``values`` is guaranteed non-empty here (the placeholder-free case
        # returned ``repr(expr)`` above), so the '%'-escape is always undone.
        code = repr(FORMAT_REGEX.sub("%s", expr.replace("%", "%%")))
        return code + f" % ({', '.join(values)},)"

    def _compile_dict_merge(self, target: str, expr: str, level: int) -> str:
        """Emit code that merges the value of ``expr`` into the ``target`` dict.

        The value may be a dict, a single ``(key, value)`` pair, or an iterable
        of such pairs. Shared codegen for ``t-att`` (merging into ``attrs``) and
        ``t-args`` (merging into ``t_call_values``).
        """
        return indent_code(
            f"""
            atts_value = {self._compile_expr(expr)}
            if isinstance(atts_value, dict):
                {target}.update(atts_value)
            elif isinstance(atts_value, (list, tuple)) and atts_value and not isinstance(atts_value[0], (list, tuple)):
                {target}.update([atts_value])
            elif isinstance(atts_value, (list, tuple)):
                {target}.update(dict(atts_value))
            """,
            level,
        )

    def _compile_expr_tokens(
        self,
        tokens: list[tokenize.TokenInfo],
        allowed_keys: list[str] | frozenset[str],
        argument_names: list[str] | None = None,
        raise_on_missing: bool = False,
    ) -> str:
        """Transform the list of tokens into a python instruction in textual
        form by namespacing the dynamic values.

        Example: `5 + a + b.c` to be `5 + values.get('a') + values['b'].c`
        Unknown values are considered to be None, but using `values['b']`
        gives a clear error message in cases where there is an attribute for
        example (have a `KeyError: 'b'`, instead of `AttributeError: 'NoneType'
        object has no attribute 'c'`).

        :rtype: str
        """
        # Finds and extracts the current "scope"'s "allowed values": values
        # which should not be accessed through the environment's namespace:
        # * the local variables of a lambda should be accessed directly e.g.
        #     lambda a: a + b should be compiled to lambda a: a + values['b'],
        #     since a is local to the lambda it has to be accessed directly
        #     but b needs to be accessed through the rendering environment
        # * similarly for a comprehensions [a + b for a in c] should be
        #     compiled to [a + values.get('b') for a in values.get('c')]
        # to avoid the risk of confusion between nested lambdas / comprehensions,
        # this is currently performed independently at each level of brackets
        # nesting (hence the function being recursive).
        bracket_depth = 0

        argument_name = "_arg_%s__"
        argument_names = argument_names or []

        for index, t in enumerate(tokens):
            if t.exact_type in [token.LPAR, token.LSQB, token.LBRACE]:
                bracket_depth += 1
            elif t.exact_type in [token.RPAR, token.RSQB, token.RBRACE]:
                bracket_depth -= 1
            elif bracket_depth == 0 and t.exact_type == token.NAME:
                string = t.string
                if (
                    string == "lambda"
                ):  # lambda => allowed values for the current bracket depth
                    for i in range(index + 1, len(tokens)):
                        t = tokens[i]
                        if t.exact_type == token.NAME:
                            argument_names.append(t.string)
                        elif t.exact_type == token.COMMA:
                            pass
                        elif t.exact_type == token.COLON:
                            break
                        elif t.exact_type == token.EQUAL:
                            msg = "Lambda default values are not supported"
                            raise NotImplementedError(msg)
                        else:
                            msg = "This lambda code style is not implemented."
                            raise NotImplementedError(msg)
                elif (
                    string == "for"
                ):  # list comprehensions => allowed values for the current bracket depth
                    for i in range(index + 1, len(tokens)):
                        t = tokens[i]
                        if t.exact_type == token.NAME:
                            if t.string == "in":
                                break
                            argument_names.append(t.string)
                        elif t.exact_type in [
                            token.COMMA,
                            token.LPAR,
                            token.RPAR,
                        ]:
                            pass
                        else:
                            msg = "This loop code style is not implemented."
                            raise NotImplementedError(msg)

        # Use bracket to nest structures.
        # Recursively processes the "sub-scopes", and replace their content with
        # a compiled node. During this recursive call we add to the allowed
        # values the values provided by the list comprehension, lambda, etc.,
        # previously extracted.
        index = 0
        open_bracket_index = -1
        bracket_depth = 0

        while index < len(tokens):
            t = tokens[index]
            string = t.string

            if t.exact_type in [token.LPAR, token.LSQB, token.LBRACE]:
                if bracket_depth == 0:
                    open_bracket_index = index
                bracket_depth += 1
            elif t.exact_type in [token.RPAR, token.RSQB, token.RBRACE]:
                bracket_depth -= 1
                if bracket_depth == 0:
                    code = self._compile_expr_tokens(
                        tokens[open_bracket_index + 1 : index],
                        list(allowed_keys),
                        list(argument_names),
                        raise_on_missing,
                    )
                    code = tokens[open_bracket_index].string + code + t.string
                    tokens[open_bracket_index : index + 1] = [
                        tokenize.TokenInfo(
                            QWEB_TOKEN_TYPE,
                            code,
                            tokens[open_bracket_index].start,
                            t.end,
                            "",
                        )
                    ]
                    index = open_bracket_index

            index += 1

        # The keys will be namespaced by values if they are not allowed. In
        # order to have a clear keyError message, this will be replaced by
        # values['key'] for certain cases (for example if an attribute is called
        # key.attrib, or an index key[0] ...)
        code = []
        index = 0
        pos = tokens and tokens[0].start  # to keep level when use expr on multi line
        while index < len(tokens):
            t = tokens[index]
            string = t.string

            if t.start[0] != pos[0]:
                pos = (t.start[0], 0)
            space = t.start[1] - pos[1]
            if space:
                code.append(" " * space)
            pos = t.start

            if t.exact_type == token.NAME:
                if "__" in string:
                    raise SyntaxError(
                        f"Using variable names with '__' is not allowed: {string!r}"
                    )
                if string == "lambda":  # lambda => allowed values
                    code.append("lambda ")
                    index += 1
                    while index < len(tokens):
                        t = tokens[index]
                        if t.exact_type == token.NAME and t.string in argument_names:
                            code.append(argument_name % t.string)
                        if t.exact_type in [token.COMMA, token.COLON]:
                            code.append(t.string)
                        if t.exact_type == token.COLON:
                            break
                        index += 1
                    if t.end[0] != pos[0]:
                        pos = (t.end[0], 0)
                    else:
                        pos = t.end
                elif string in argument_names:
                    code.append(argument_name % t.string)
                elif (
                    string in allowed_keys
                    or (
                        index + 1 < len(tokens)
                        and tokens[index + 1].exact_type == token.EQUAL
                    )
                    or (
                        index > 0
                        and tokens[index - 1]
                        and tokens[index - 1].exact_type == token.DOT
                    )
                ):
                    code.append(string)
                elif raise_on_missing or (
                    index + 1 < len(tokens)
                    and tokens[index + 1].exact_type
                    in [token.DOT, token.LPAR, token.LSQB, QWEB_TOKEN_TYPE]
                ):
                    # Should have values['product'].price to raise an error when get
                    # the 'product' value and not an 'NoneType' object has no
                    # attribute 'price' error.
                    code.append(f"values[{string!r}]")
                else:
                    # not assignation allowed, only getter
                    code.append(f"values.get({string!r})")
            elif t.type not in [
                tokenize.ENCODING,
                token.ENDMARKER,
                token.DEDENT,
            ]:
                code.append(string)

            if t.end[0] != pos[0]:
                pos = (t.end[0], 0)
            else:
                pos = t.end

            index += 1

        return "".join(code)

    # Cache for _compile_expr: (expr, raise_on_missing) → compiled expression string.
    # Deterministic (no instance state). An LRU (not a dict cleared wholesale at the
    # cap) avoids a full-recompile stampede once distinct expressions exceed the cap;
    # _compile_expr runs only at compile time, off the warm render path (QWEB-P1).
    _compile_expr_cache = LRU(8192)

    def _compile_expr(self, expr: str, raise_on_missing: bool = False) -> str:
        """Transform a string into a python instruction in textual form by
        namespacing the dynamic values.
        Tokenizes the string and calls ``_compile_expr_tokens``.

        :param str expr: python expression
        :param bool raise_on_missing:
            Compile has `values['product'].price` instead of
            `values.get('product').price` to raise an error when get the
            'product' value and not an 'NoneType' object has no attribute
            'price' error.
        """
        cache_key = (expr, raise_on_missing)
        result = self._compile_expr_cache.get(cache_key)
        if result is not None:
            return result

        # Parentheses are useful for compiling multi-line expressions such as
        # conditions existing in some templates. (see test_compile_expr tests)
        readable = io.BytesIO(f"({expr or ''})".encode())
        try:
            tokens = list(tokenize.tokenize(readable.readline))
        except tokenize.TokenError as e:
            # Keep the tokenizer's own detail (message + position) instead of
            # discarding it: it points at the offending spot in the template
            # expression.
            raise ValueError(f"Can not compile expression: {expr} ({e.args[0]})") from e

        expression = self._compile_expr_tokens(
            tokens, ALLOWED_KEYWORD, raise_on_missing=raise_on_missing
        )

        assert_valid_codeobj(
            _SAFE_QWEB_OPCODES, compile(expression, "<>", "eval"), expr
        )

        result = f"({expression})"
        self._compile_expr_cache[cache_key] = result
        return result

    def _compile_bool(self, attr: str | bool | None, default: bool = False) -> bool:
        """Convert the statements as a boolean."""
        if attr:
            if attr is True:
                return True
            attr = attr.lower()
            if attr in ("false", "0"):
                return False
            elif attr in ("true", "1"):
                return True
        return bool(default)

    def _compile_to_str(self, expr: Any) -> str:
        """Generate a string from an arbitrary source."""
        if expr is None or expr is False:
            return ""

        if isinstance(expr, str):
            return expr
        elif isinstance(expr, bytes):
            return expr.decode()
        else:
            return str(expr)

    # order

    def _directives_eval_order(self) -> list[str]:
        """List all supported directives in the order in which they should be
        evaluated on a given element. For instance, a node bearing both
        ``foreach`` and ``if`` should see ``foreach`` executed before ``if``
        aka

        .. code-block:: xml

            <el t-foreach="foo" t-as="bar" t-if="bar">

        should be equivalent to

        .. code-block:: xml

            <t t-foreach="foo" t-as="bar">
                <t t-if="bar">
                    <el>

        then this method should return ``['foreach', 'if']``.
        """
        return [
            "elif",  # Must be the first because compiled by the previous if.
            "else",  # Must be the first because compiled by the previous if.
            "debug",
            "groups",
            "as",
            "foreach",
            "if",
            "call-assets",
            "lang",
            "options",
            "call",
            "att",
            "field",
            "esc",
            "raw",
            "out",
            "tag-open",
            "set",
            "inner-content",
            "tag-close",
        ]

    # compile

    def _compile_node(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile the given element into python code.

        The t-* attributes (directives) are converted to python instructions. If
        there are no t-* attributes, the element is considered static.

        Directives are compiled in the order given by ``_directives_eval_order``
        (which creates the ``compile_context['iter_directives']`` iterator). Only
        directives with a ``_compile_directive_*`` method are supported.

        :return: list of string
        """
        # Internal directive used to skip a rendering.
        if "t-qweb-skip" in el.attrib:
            return []

        # if tag don't have qweb attributes don't use directives
        if self._is_static_node(el, compile_context):
            return self._compile_static_node(el, compile_context, level)

        path = compile_context["root"].getpath(el)
        xml = etree.tostring(etree.Element(el.tag, el.attrib), encoding="unicode")
        compile_context["_qweb_error_path_xml"][0] = compile_context["ref"]
        compile_context["_qweb_error_path_xml"][1] = path
        compile_context["_qweb_error_path_xml"][2] = xml
        body = [indent_code(self._element_marker(path, xml), level)]

        # create an iterator on directives to compile in order
        compile_context["iter_directives"] = iter(self._directives_eval_order())

        # add technical directive tag-open, tag-close, inner-content and take
        # care of the namespace
        if not el.nsmap:
            unqualified_el_tag = el_tag = el.tag
        else:
            # Etree will remove the ns prefixes indirection by inlining the corresponding
            # nsmap definition into the tag attribute. Restore the tag and prefix here.
            # Note: we do not support namespace dynamic attributes, we need a default URI
            # on the root and use attribute directive t-att="{'xmlns:example': value}".
            unqualified_el_tag = etree.QName(el.tag).localname
            el_tag = unqualified_el_tag
            if el.prefix:
                el_tag = f"{el.prefix}:{el_tag}"

        if unqualified_el_tag != "t":
            el.set("t-tag-open", el_tag)
            if el_tag not in VOID_ELEMENTS:
                el.set("t-tag-close", el_tag)

        if not ({"t-out", "t-esc", "t-raw", "t-field"} & set(el.attrib)):
            el.set("t-inner-content", "True")

        return body + self._compile_directives(el, compile_context, level)

    def _compile_static_node(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile a purely static element into a list of string."""
        if not el.nsmap:
            unqualified_el_tag = el_tag = el.tag
            attrib = self._post_processing_att(el.tag, dict(el.attrib), is_static=True)
        else:
            # Etree will remove the ns prefixes indirection by inlining the corresponding
            # nsmap definition into the tag attribute. Restore the tag and prefix here.
            unqualified_el_tag = etree.QName(el.tag).localname
            el_tag = unqualified_el_tag
            if el.prefix:
                el_tag = f"{el.prefix}:{el_tag}"

            attrib = {}
            # If `el` introduced new namespaces, write them as attribute by using the
            # `attrib` dict.
            for ns_prefix, ns_definition in self._new_namespaces(el, compile_context):
                if ns_prefix is None:
                    attrib["xmlns"] = ns_definition
                else:
                    attrib[f"xmlns:{ns_prefix}"] = ns_definition

            # Etree will also remove the ns prefixes indirection in the attributes. As we only have
            # the namespace definition, we'll use an nsmap where the keys are the definitions and
            # the values the prefixes in order to get back the right prefix and restore it.
            nsprefixmap = self._ns_prefix_map(el, compile_context)
            for key, value in el.attrib.items():
                name = key.removesuffix(".translate")
                attrib_qname = etree.QName(name)
                if attrib_qname.namespace:
                    attrib[
                        f"{nsprefixmap[attrib_qname.namespace]}:{attrib_qname.localname}"
                    ] = value
                else:
                    attrib[name] = value

            attrib = self._post_processing_att(el.tag, attrib, is_static=True)

            # Update the dict of inherited namespaces before continuing the recursion. Note:
            # since `compile_context['nsmap']` is a dict (and therefore mutable) and we do **not**
            # want changes done in deeper recursion to be visible in earlier ones, we'll pass
            # a copy before continuing the recursion and restore the original afterwards.
            original_nsmap = dict(compile_context["nsmap"])

        if unqualified_el_tag != "t":
            attributes = "".join(
                f' {name.removesuffix(".translate")}="{escape(str(value))}"'
                for name, value in attrib.items()
                if value or isinstance(value, str)
            )
            self._append_text(f"<{el_tag}{attributes}", compile_context)
            if el_tag in VOID_ELEMENTS:
                self._append_text("/>", compile_context)
            else:
                self._append_text(">", compile_context)

        el.attrib.clear()

        if el.nsmap:
            compile_context["nsmap"].update(el.nsmap)
            body = self._compile_directive(el, compile_context, "inner-content", level)
            compile_context["nsmap"] = original_nsmap
        else:
            body = self._compile_directive(el, compile_context, "inner-content", level)

        if unqualified_el_tag != "t":
            if el_tag not in VOID_ELEMENTS:
                self._append_text(f"</{el_tag}>", compile_context)

        return body

    def _compile_directives(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile the given element, following the directives given in the
        iterator ``compile_context['iter_directives']`` created by
        ``_compile_node``.

        :return: list of code lines
        """
        # Re-checked here (already tested in ``_compile_node``) because the
        # ``if``/``foreach``/``groups`` directives recurse back into
        # ``_compile_directives`` on the *same* element after popping their own
        # attribute: the node may have become static in the meantime, in which
        # case the leftover technical directives are dropped and it is emitted
        # as a static node.
        if self._is_static_node(el, compile_context):
            el.attrib.pop("t-tag-open", None)
            el.attrib.pop("t-inner-content", None)
            el.attrib.pop("t-tag-close", None)
            return self._compile_static_node(el, compile_context, level)

        code = []

        # compile the directives still present on the element, in the order
        # given by ``iter_directives``. A directive is compiled when its
        # attribute is present (``t-<directive>``), plus three special cases:
        # ``att`` runs unconditionally (it seeds ``__qweb_attrs__`` even with no
        # attributes), ``groups`` also accepts the bare ``groups`` alias, and
        # ``options`` fires on any ``t-options-*`` attribute.
        for directive in compile_context["iter_directives"]:
            if (
                ("t-" + directive) in el.attrib
                or directive == "att"
                or (directive == "groups" and "groups" in el.attrib)
                or (
                    directive == "options"
                    and any(name.startswith("t-options-") for name in el.attrib)
                )
            ):
                code.extend(
                    self._compile_directive(el, compile_context, directive, level)
                )

        # compile unordered directives still present on the element
        for att in el.attrib:
            if (
                att not in SPECIAL_DIRECTIVES
                and att.startswith("t-")
                and getattr(
                    self,
                    f"_compile_directive_{att[2:].replace('-', '_')}",
                    None,
                )
            ):
                code.extend(
                    self._compile_directive(el, compile_context, att[2:], level)
                )

        remaining = set(el.attrib) - SPECIAL_DIRECTIVES
        if remaining:
            _logger.warning(
                "Unknown directives or unused attributes: %s in %s",
                remaining,
                compile_context["template"],
            )

        return code

    def _compile_directive(
        self,
        el: etree._Element,
        compile_context: dict[str, Any],
        directive: str,
        level: int,
    ) -> list[str]:
        compile_handler = getattr(
            self, f"_compile_directive_{directive.replace('-', '_')}", None
        )
        if compile_context.get("profile") and directive not in (
            "inner-content",
            "tag-open",
            "tag-close",
        ):
            enter = f"{' ' * 4 * level}self.env.context['qweb_tracker'].enter_directive({directive!r}, {el.attrib!r}, {compile_context['_qweb_error_path_xml'][1]!r})"
            leave = f"{' ' * 4 * level}self.env.context['qweb_tracker'].leave_directive({directive!r}, {el.attrib!r}, {compile_context['_qweb_error_path_xml'][1]!r})"
            code_directive = compile_handler(el, compile_context, level)
            if code_directive:
                code_directive = [enter, *code_directive, leave]
        else:
            code_directive = compile_handler(el, compile_context, level)
        return code_directive

    # compile directives

    def _compile_directive_debug(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile ``t-debug`` into a call to the chosen debugger (dev mode only)."""
        debugger = el.attrib.pop("t-debug")
        code = []
        if compile_context.get("dev_mode"):
            code.append(indent_code(f"self._debug_trace({debugger!r}, values)", level))
        else:
            _logger.warning("@t-debug in template is only available in qweb dev mode")
        return code

    def _compile_directive_options(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile ``t-options`` and the ``t-options-*`` attributes, creating
        the ``values['__qweb_options__']`` dictionary in the compiled code.
        """
        code = []
        dict_options = []
        for key in list(el.attrib):
            if key.startswith("t-options-"):
                value = el.attrib.pop(key)
                option_name = key.removeprefix("t-options-")
                dict_options.append(f"{option_name!r}:{self._compile_expr(value)}")

        t_options = el.attrib.pop("t-options", None)
        if t_options and dict_options:
            code.append(
                indent_code(
                    f"values['__qweb_options__'] = {{**{self._compile_expr(t_options)}, {', '.join(dict_options)}}}",
                    level,
                )
            )
        elif dict_options:
            code.append(
                indent_code(
                    f"values['__qweb_options__'] = {{{', '.join(dict_options)}}}",
                    level,
                )
            )
        elif t_options:
            code.append(
                indent_code(
                    f"values['__qweb_options__'] = {self._compile_expr(t_options)}",
                    level,
                )
            )
        else:
            code.append(indent_code("values['__qweb_options__'] = {}", level))

        # Marker consumed by ``_compile_directive_out`` (and popped by
        # ``t-call``); ``_compile_directive_consumed_options`` raises if it is
        # still present after all directives ran. Every branch above appends
        # code, so the marker is unconditional.
        el.set("t-consumed-options", "True")

        return code

    def _compile_directive_consumed_options(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        msg = "the t-options must be on the same tag as a directive that consumes it (for example: t-out, t-field, t-call)"
        raise SyntaxError(msg)

    def _compile_directive_att(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile the attributes of the given element.

        The compiled function creates and fills the ``values['__qweb_attrs__']``
        dictionary (output later by the ``t-tag-open`` directive) with, in order:

        - the new namespaces introduced by the current element;
        - the static attributes (not prefixed by ``t-``);
        - the dynamic attributes:

          - ``t-att``: python dictionary expression;
          - ``t-att-*``: python expression;
          - ``t-attf-*``: format string expression.
        """
        code = [indent_code("attrs = values['__qweb_attrs__'] = {}", level)]

        # Compile the introduced new namespaces of the given element.
        #
        # Add the found new attributes into the `attrs` dictionary like
        # the static attributes.
        if el.nsmap:
            for ns_prefix, ns_definition in self._new_namespaces(el, compile_context):
                key = "xmlns"
                if ns_prefix is not None:
                    key = f"xmlns:{ns_prefix}"
                code.append(indent_code(f"attrs[{key!r}] = {ns_definition!r}", level))

        # Compile the static attributes of the given element.
        #
        # Etree will also remove the ns prefixes indirection in the
        # attributes. As we only have the namespace definition, we'll use
        # an nsmap where the keys are the definitions and the values the
        # prefixes in order to get back the right prefix and restore it.
        if any(not key.startswith("t-") for key in el.attrib):
            nsprefixmap = self._ns_prefix_map(el, compile_context)
            for key in list(el.attrib):
                if not key.startswith("t-"):
                    value = el.attrib.pop(key)
                    name = key.removesuffix(".translate")
                    attrib_qname = etree.QName(name)
                    if attrib_qname.namespace:
                        name = f"{nsprefixmap[attrib_qname.namespace]}:{attrib_qname.localname}"
                    code.append(indent_code(f"attrs[{name!r}] = {value!r}", level))

        # Compile the dynamic attributes of the given element. All
        # attributes will be add to the ``attrs`` dictionary in the
        # compiled function.
        for key in list(el.attrib):
            if key.startswith("t-attf-"):
                value = el.attrib.pop(key)
                name = key[7:].removesuffix(".translate")
                code.append(
                    indent_code(
                        f"attrs[{name!r}] = {self._compile_format(value)}",
                        level,
                    )
                )
            elif key.startswith("t-att-"):
                value = el.attrib.pop(key)
                code.append(
                    indent_code(
                        f"attrs[{key.removeprefix('t-att-')!r}] = {self._compile_expr(value)}",
                        level,
                    )
                )
            elif key == "t-att":
                value = el.attrib.pop(key)
                code.append(self._compile_dict_merge("attrs", value, level))

        return code

    def _compile_directive_tag_open(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile the opening tag of the given element into python code.

        The compiled function outputs the open tag, then post-processes and
        outputs the attributes from the ``attrs`` dictionary (built by the
        ``t-att`` directive), consuming and resetting it.
        """

        el_tag = el.attrib.pop("t-tag-open", None)
        if not el_tag:
            return []

        # open the open tag
        self._append_text(f"<{el_tag}", compile_context)

        code = self._flush_text(compile_context, level)

        # Generates the part of the code that post-process and output the
        # attributes from ``attrs`` dictionary. Consumes `attrs` dictionary
        # and reset it.
        #
        # Use str(value) to change Markup into str and escape it, then use str
        # to avoid the escaping of the other html content.
        code.append(
            indent_code(
                f"""
            attrs = values.pop('__qweb_attrs__', None)
            if attrs:
                tagName = {el.tag!r}
                attrs = self._post_processing_att(tagName, attrs)
                for name, value in attrs.items():
                    if value or isinstance(value, str):
                        yield f' {{escape(str(name))}}="{{escape(str(value))}}"'
        """,
                level,
            )
        )

        # close the open tag
        if "t-tag-close" in el.attrib:
            self._append_text(">", compile_context)
        else:
            self._append_text("/>", compile_context)

        return code

    def _compile_directive_tag_close(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Queue the element's closing tag via ``_append_text`` (returns no code)."""
        el_tag = el.attrib.pop("t-tag-close", None)
        if el_tag:
            self._append_text(f"</{el_tag}>", compile_context)
        return []

    def _compile_directive_set(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile `t-set` expressions into a python code as a list of
        strings.

        There are different kinds of `t-set`:
        * `t-value` containing python code;
        * `t-valuef` containing strings to format;
        * `t-valuef.translate` containing translated strings to format;
        * whose value is the content of the tag (being Markup safe).

        The code will contain the assignment of the dynamically generated value.
        """

        code = self._flush_text(compile_context, level, rstrip=el.tag.lower() == "t")

        if "t-set" in el.attrib:
            varname = el.attrib.pop("t-set")
            if varname == "":
                msg = "t-set"
                raise KeyError(msg)
            if (
                varname != T_CALL_SLOT
                and varname[0] != "{"
                and not VARNAME_REGEXP.match(varname)
            ):
                msg = "The varname can only contain alphanumeric characters and underscores."
                raise SyntaxError(msg)
            if "__" in varname:
                raise SyntaxError(
                    f"Using variable names with '__' is not allowed: {varname!r}"
                )

            if (
                "t-value" in el.attrib
                or "t-valuef" in el.attrib
                or "t-valuef.translate" in el.attrib
                or varname[0] == "{"
            ):
                el.attrib.pop("t-inner-content")  # The content is considered empty.
                if varname == T_CALL_SLOT:
                    msg = 't-set="0" should not be set from t-value or t-valuef'
                    raise SyntaxError(msg)

            if "t-value" in el.attrib:
                expr = el.attrib.pop("t-value") or "None"
                code.append(
                    indent_code(
                        f"values[{varname!r}] = {self._compile_expr(expr)}",
                        level,
                    )
                )
            elif "t-valuef" in el.attrib:
                exprf = el.attrib.pop("t-valuef")
                code.append(
                    indent_code(
                        f"values[{varname!r}] = {self._compile_format(exprf)}",
                        level,
                    )
                )
            elif "t-valuef.translate" in el.attrib:
                exprf = el.attrib.pop("t-valuef.translate")
                if self.env.context.get("edit_translations"):
                    code.append(
                        indent_code(
                            f"values[{varname!r}] = Markup({self._compile_format(exprf)})",
                            level,
                        )
                    )
                else:
                    code.append(
                        indent_code(
                            f"values[{varname!r}] = {self._compile_format(exprf)}",
                            level,
                        )
                    )
            elif varname[0] == "{":
                code.append(
                    indent_code(f"values.update({self._compile_expr(varname)})", level)
                )
            else:
                # set the content as value
                _ref, path, xml = compile_context["_qweb_error_path_xml"]
                content = self._compile_directive(
                    el, compile_context, "inner-content", 1
                ) + self._flush_text(compile_context, 1)
                if content:
                    def_name = compile_context["make_name"]("t_set")
                    def_code = [f"def {def_name}(self, values):"]
                    def_code.append(indent_code(self._element_marker(path, xml), 1))
                    def_code.extend(content)
                    compile_context["template_functions"][def_name] = def_code

                    code.append(
                        indent_code(
                            f"""
                        values[{varname!r}] = QwebContent(self, QwebCallParameters(self.env.context, {compile_context["ref"]!r}, {def_name!r}, values.copy(), 'root', 't-set', (template_options['ref'], {path!r}, {xml!r})))
                    """,
                            level,
                        )
                    )
                else:
                    code.append(indent_code(f"values[{varname!r}] = ''", level))

        return code

    def _compile_directive_value(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Only checks that ``t-value`` is on the same node as ``t-set``."""
        msg = "t-value must be on the same node of t-set"
        raise SyntaxError(msg)

    def _compile_directive_valuef(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Only checks that ``t-valuef`` is on the same node as ``t-set``."""
        msg = "t-valuef must be on the same node of t-set"
        raise SyntaxError(msg)

    def _compile_directive_inner_content(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile the content of the element (the technical ``t-inner-content``
        directive created by QWeb) into python code as a list of strings.

        The code contains the text content of the node and the compiled code
        from the recursive ``_compile_node`` calls on its children.
        """
        el.attrib.pop("t-inner-content", None)

        if el.nsmap:
            # Update the dict of inherited namespaces before continuing the recursion. Note:
            # since `compile_context['nsmap']` is a dict (and therefore mutable) and we do **not**
            # want changes done in deeper recursion to be visible in earlier ones, we'll pass
            # a copy before continuing the recursion and restore the original afterwards.
            compile_context = dict(compile_context, nsmap=el.nsmap)

        if el.text is not None:
            self._append_text(el.text, compile_context)
        body = []
        for item in list(el):
            if isinstance(item, etree._Comment):
                if compile_context.get("preserve_comments"):
                    self._append_text(f"<!--{item.text}-->", compile_context)
                else:
                    # When removing a comment, strip trailing indentation
                    # (spaces/tabs) from the preceding text chunk if it's
                    # purely whitespace, so blank lines don't keep invisible
                    # trailing spaces.
                    self._strip_pending_trailing_ws(compile_context)
                    # Comments removed from the DOM by _compile_directive_if
                    # (between t-if and t-else/t-elif) need their tail
                    # indentation stripped too, since the surrounding
                    # whitespace is no longer meaningful.
                    if item.getparent() is None and item.tail is not None:
                        tail = item.tail
                        if tail.isspace():
                            tail = tail.rstrip(" \t")
                        if tail:
                            self._append_text(tail, compile_context)
                        continue
            elif isinstance(item, etree._ProcessingInstruction):
                if compile_context.get("preserve_comments"):
                    self._append_text(f"<?{item.target} {item.text}?>", compile_context)
                else:
                    self._strip_pending_trailing_ws(compile_context)
            else:
                body.extend(self._compile_node(item, compile_context, level))
            # comments can also contains tail text
            if item.tail is not None:
                self._append_text(item.tail, compile_context)
        return body

    def _compile_directive_if(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile ``t-if`` (with any following ``t-else``/``t-elif``) into an
        ``if``/``elif``/``else`` wrapping the element's compiled content.
        """
        expr = el.attrib.pop("t-if", el.attrib.pop("t-elif", None))

        if not expr or not expr.strip():
            raise ValueError("t-if or t-elif expression should not be empty.")

        strip = self._rstrip_text(
            compile_context
        )  # the whitespace is visible only when displaying content
        if el.tag.lower() == "t" and el.text and LSTRIP_REGEXP.search(el.text):
            strip = ""  # remove technical spaces
        code = self._flush_text(compile_context, level)

        code.append(indent_code(f"if {self._compile_expr(expr)}:", level))
        body = []
        if strip:
            self._append_text(strip, compile_context)
        body.extend(
            self._compile_directives(el, compile_context, level + 1)
            + self._flush_text(compile_context, level + 1, rstrip=True)
        )
        code.extend(body or [indent_code("pass", level + 1)])

        # Look for the else or elif conditions
        next_el = el.getnext()
        comments_to_remove = []
        while isinstance(next_el, etree._Comment):
            comments_to_remove.append(next_el)
            next_el = next_el.getnext()

        # If there is a t-else directive, the comment nodes are deleted
        # and the t-else or t-elif is validated.
        if next_el is not None and {"t-else", "t-elif"} & set(next_el.attrib):
            # Insert a flag to allow t-else or t-elif rendering.
            next_el.attrib["t-else-valid"] = "True"

            # remove comment node
            parent = el.getparent()
            for comment in comments_to_remove:
                parent.remove(comment)
            if el.tail and not el.tail.isspace():
                msg = "Unexpected non-whitespace characters between t-if and t-else directives"
                raise SyntaxError(msg)
            el.tail = None

            # You have to render the `t-else` and `t-elif` here in order
            # to be able to put the log. Otherwise, the parent's
            # `t-inner-content`` directive will render the different
            # nodes without taking indentation into account such as:
            #    if (if_expression):
            #         content_if
            #    log ['last_path_node'] = path
            #    else:
            #       content_else

            code.append(indent_code("else:", level))
            body = []
            if strip:
                self._append_text(strip, compile_context)
            body.extend(
                self._compile_node(next_el, compile_context, level + 1)
                + self._flush_text(compile_context, level + 1, rstrip=True)
            )
            code.extend(body or [indent_code("pass", level + 1)])

            # Insert a flag to avoid the t-else or t-elif rendering when
            # the parent t-inner-content directive compiles its
            # children.
            next_el.attrib["t-qweb-skip"] = "True"

        return code

    def _compile_directive_elif(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Validate that this node follows a ``t-if``/``t-elif`` (the
        ``t-else-valid`` flag) and delegate to the ``t-if`` compilation.
        """
        if not el.attrib.pop("t-else-valid", None):
            msg = "t-elif directive must be preceded by t-if or t-elif directive"
            raise SyntaxError(msg)

        return self._compile_directive_if(el, compile_context, level)

    def _compile_directive_else(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Validate that this node follows a ``t-if``/``t-elif`` (the
        ``t-else-valid`` flag); produces no code of its own.
        """
        if not el.attrib.pop("t-else-valid", None):
            msg = "t-else directive must be preceded by t-if or t-elif directive"
            raise SyntaxError(msg)
        el.attrib.pop("t-else")
        return []

    def _compile_directive_groups(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile ``t-groups`` into a ``has_groups`` check wrapping the element's
        compiled content.
        """
        groups = el.attrib.pop("t-groups", el.attrib.pop("groups", None))

        strip = self._rstrip_text(compile_context)
        code = self._flush_text(compile_context, level)
        code.append(indent_code(f"if self.env.user.has_groups({groups!r}):", level))
        if strip and el.tag.lower() != "t":
            self._append_text(strip, compile_context)
        code.extend(
            [
                *self._compile_directives(el, compile_context, level + 1),
                *self._flush_text(compile_context, level + 1, rstrip=True),
            ]
            or [indent_code("pass", level + 1)]
        )
        return code

    def _compile_directive_foreach(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile ``t-foreach`` expressions into a python code as a list of
        strings.

        * ``t-as`` is used to define the key name.
        * ``t-foreach`` compiled value can be an iterable, a dictionary or a
          number.

        The code will contain a ``for`` loop that wraps the rest of the compiled
        code of this element.

        Some keys in the values dictionary are created automatically::

            *_size, *_index, *_value, *_first, *_last, *_odd, *_even, *_parity
        """
        expr_foreach = el.attrib.pop("t-foreach")
        expr_as = el.attrib.pop("t-as")

        if not expr_as:
            msg = "t-as"
            raise KeyError(msg)

        if not VARNAME_REGEXP.match(expr_as):
            raise ValueError(
                f"The varname {expr_as!r} can only contain alphanumeric characters and underscores."
            )

        if el.tag.lower() == "t":
            self._rstrip_text(compile_context)

        code = self._flush_text(compile_context, level)

        content_foreach = self._compile_directives(
            el, compile_context, level + 1
        ) + self._flush_text(compile_context, level + 1, rstrip=True)

        t_foreach = compile_context["make_name"]("t_foreach")
        size = compile_context["make_name"]("size")
        has_value = compile_context["make_name"]("has_value")

        if expr_foreach.isdigit():
            code.append(
                indent_code(
                    f"""
                values[{expr_as + "_size"!r}] = {size} = {int(expr_foreach)}
                {t_foreach} = range({size})
                {has_value} = False
            """,
                    level,
                )
            )
        else:
            code.append(
                indent_code(
                    f"""
                {t_foreach} = {self._compile_expr(expr_foreach)} or []
                if isinstance({t_foreach}, Sized):
                    values[{expr_as + "_size"!r}] = {size} = len({t_foreach})
                elif ({t_foreach}).__class__ == int:
                    values[{expr_as + "_size"!r}] = {size} = {t_foreach}
                    {t_foreach} = range({size})
                else:
                    {size} = None
                {has_value} = False
                if isinstance({t_foreach}, Mapping):
                    {t_foreach} = {t_foreach}.items()
                    {has_value} = True
            """,
                    level,
                )
            )

        code.append(
            indent_code(
                f"""
                for index, item in enumerate({t_foreach}):
                    values[{expr_as + "_index"!r}] = index
                    if {has_value}:
                        values[{expr_as!r}], values[{expr_as + "_value"!r}] = item
                    else:
                        values[{expr_as!r}] = values[{expr_as + "_value"!r}] = item
                    values[{expr_as + "_first"!r}] = values[{expr_as + "_index"!r}] == 0
                    if {size} is not None:
                        values[{expr_as + "_last"!r}] = index + 1 == {size}
                    else:
                        # Lazy iterables (generators: not Sized/int/Mapping) have no
                        # knowable last element. Assign False every iteration anyway,
                        # so a caller-provided or outer-loop ``*_last`` cannot leak
                        # into the loop body (see test_foreach_lazy_last_no_leak).
                        values[{expr_as + "_last"!r}] = False
                    values[{expr_as + "_odd"!r}] = index % 2
                    values[{expr_as + "_even"!r}] = not values[{expr_as + "_odd"!r}]
                    values[{expr_as + "_parity"!r}] = 'odd' if values[{expr_as + "_odd"!r}] else 'even'
            """,
                level,
            )
        )

        # Wrap the fallback in a list like the ``if``/``groups`` directives:
        # ``indent_code`` returns a str, so ``code.extend(str)`` would splice it
        # character-by-character into broken Python. Harmless today only because
        # ``_compile_directive_att`` always emits a line — don't rely on that here.
        code.extend(content_foreach or [indent_code("continue", level + 1)])

        return code

    def _compile_directive_as(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Only checks that ``t-as`` is on the same node as ``t-foreach``."""
        if "t-foreach" not in el.attrib:
            msg = "t-as must be on the same node of t-foreach"
            raise SyntaxError(msg)
        return []

    def _compile_directive_out(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile `t-out` expressions into a python code as a list of
        strings.

        The code will contain evaluation and rendering of the compiled value. If
        the compiled value is None or False, the tag is not added to the render
        (Except if the widget forces rendering or there is default content).
        (eg: `<t t-out="my_value">Default content if falsy</t>`)

        The output can have some rendering option with `t-options-widget` or
        `t-options={'widget': ...}. At rendering time, The compiled code will
        call ``_get_widget`` method or ``_get_field`` method for `t-field`.

        A `t-field` will necessarily be linked to the value of a record field
        (eg: `<span t-field="record.field_name"/>`), a t-out` can be applied
        to any value (eg: `<span t-out="10" t-options-widget="'float'"/>`).
        """
        ttype, expr = self._compile_out_target(el)

        code = self._flush_text(compile_context, level)

        _ref, path, xml = compile_context["_qweb_error_path_xml"]

        has_options = el.attrib.pop("t-consumed-options", None) is not None
        tag_open = self._compile_directive(
            el, compile_context, "tag-open", level + 1
        ) + self._flush_text(compile_context, level + 1)
        tag_close = self._compile_directive(
            el, compile_context, "tag-close", level + 1
        ) + self._flush_text(compile_context, level + 1)
        default_body = self._compile_directive(
            el, compile_context, "inner-content", level + 1
        ) + self._flush_text(compile_context, level + 1)

        # The generated code will set the values of the content, attrs (used to
        # output attributes) and the force_display (if the widget or field
        # mark force_display as True, the tag will be inserted in the output
        # even the value of content is None and without default value)

        # Fast path: the t-call content slot with no widget is emitted verbatim.
        if expr == T_CALL_SLOT and not has_options:
            code.append(indent_code("if True:", level))
            code.extend(tag_open)
            code.append(indent_code(f"yield values.get({T_CALL_SLOT}, '')", level + 1))
            code.extend(tag_close)
            return code

        set_code, force_display_dependent = self._compile_out_set_content(
            el, ttype, expr, has_options, level
        )
        code.extend(set_code)
        code.extend(
            self._compile_out_emit(
                compile_context,
                tag_open,
                tag_close,
                default_body,
                force_display_dependent,
                path,
                xml,
                level,
            )
        )
        return code

    def _compile_out_target(self, el: etree._Element) -> tuple[str, str]:
        """Pop and return the ``(ttype, expr)`` of a ``t-out`` node, resolving
        the ``t-field``/``t-esc``/``t-raw`` aliases (the latter two deprecated).
        """
        for ttype in ("t-out", "t-field", "t-esc"):
            expr = el.attrib.pop(ttype, None)
            if expr is not None:
                return ttype, expr
        return "t-raw", el.attrib.pop("t-raw")

    def _compile_out_set_content(
        self,
        el: etree._Element,
        ttype: str,
        expr: str,
        has_options: bool,
        level: int,
    ) -> tuple[list[str], bool]:
        """Emit the code that assigns ``content`` (and merges any widget/field
        attributes into ``__qweb_attrs__``) for a ``t-out``/``t-field`` node.

        :param has_options: the node carried ``t-options``/``t-options-*``
            (the ``t-consumed-options`` marker), so the value goes through
            ``_get_widget``.

        :return: ``(code_lines, force_display_dependent)`` where the flag is set
            when a widget/field may force the tag to be displayed even for a
            falsy value.
        """
        if ttype == "t-field":
            record, field_name = expr.rsplit(".", 1)
            return [
                indent_code(
                    f"""
                field_attrs, content, force_display = self._get_field({self._compile_expr(record, raise_on_missing=True)}, {field_name!r}, {expr!r}, {el.tag!r}, values.pop('__qweb_options__', {{}}), values)
                if values.get('__qweb_attrs__') is None:
                    values['__qweb_attrs__'] = field_attrs
                else:
                    values['__qweb_attrs__'].update(field_attrs)
                if content is not None and content is not False:
                    content = self._compile_to_str(content)
                """,
                    level,
                )
            ], True

        if expr == T_CALL_SLOT:
            code = [indent_code(f"content = values.get({T_CALL_SLOT}, '')", level)]
        else:
            code = [indent_code(f"content = {self._compile_expr(expr)}", level)]

        force_display_dependent = has_options
        if force_display_dependent:
            code.append(
                indent_code(
                    f"""
                widget_attrs, content, force_display = self._get_widget(content, {expr!r}, {el.tag!r}, values.pop('__qweb_options__', {{}}), values)
                if values.get('__qweb_attrs__') is None:
                    values['__qweb_attrs__'] = widget_attrs
                else:
                    values['__qweb_attrs__'].update(widget_attrs)
                content = self._compile_to_str(content)
                """,
                    level,
                )
            )

        if ttype == "t-raw":
            # deprecated use.
            code.append(
                indent_code(
                    """
                if content is not None and content is not False:
                    content = Markup(content)
                """,
                    level,
                )
            )

        return code, force_display_dependent

    def _compile_out_emit(
        self,
        compile_context: dict[str, Any],
        tag_open: list[str],
        tag_close: list[str],
        default_body: list[str],
        force_display_dependent: bool,
        path: str | None,
        xml: str | None,
        level: int,
    ) -> list[str]:
        """Emit the output tail of a ``t-out``: the tag is written when the
        value is truthy, else the default content (if any) or — for a
        force-display widget/field — the bare tag.
        """
        # generate code to display the tag if the value is not Falsy
        code = [indent_code("if content is not None and content is not False:", level)]
        code.extend(tag_open)
        # Use str to avoid the escaping of the other html content because the
        # yield generator MarkupSafe values will be join into an string in
        # `_render`.
        code.append(
            indent_code(
                f"""
            if isinstance(content, QwebContent):
                self.env.context['_qweb_error_path_xml'][0] = template_options['ref']
                self.env.context['_qweb_error_path_xml'][1] = {path!r}
                self.env.context['_qweb_error_path_xml'][2] = {xml!r}
                yield content
            else:
                yield str(escape(content))
        """,
                level + 1,
            )
        )
        code.extend(tag_close)

        # generate code to display the tag with default content if the value is
        # Falsy
        if default_body or compile_context["_text_concat"]:
            _text_concat = list(compile_context["_text_concat"])
            compile_context["_text_concat"].clear()
            code.append(indent_code("else:", level))
            code.extend(tag_open)
            code.extend(default_body)
            compile_context["_text_concat"].extend(_text_concat)
            code.extend(tag_close)
        elif force_display_dependent:
            # generate code to display the tag if it's the force_display mode.
            if tag_open + tag_close:
                code.append(indent_code("elif force_display:", level))
                code.extend(tag_open + tag_close)

            code.append(
                indent_code("""else: values.pop('__qweb_attrs__', None)""", level)
            )

        return code

    def _compile_directive_esc(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        # deprecated use.
        if compile_context.get("dev_mode"):
            _logger.warning(
                "Found deprecated directive @t-esc=%r in template %r. Replace by @t-out",
                el.get("t-esc"),
                compile_context.get("ref", "<unknown>"),
            )
        return self._compile_directive_out(el, compile_context, level)

    def _compile_directive_raw(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        # deprecated use.
        _logger.warning(
            "Found deprecated directive @t-raw=%r in template %r. Replace by "
            "@t-out, and explicitely wrap content in `Markup` if "
            "necessary (which likely is not the case)",
            el.get("t-raw"),
            compile_context.get("ref", "<unknown>"),
        )
        return self._compile_directive_out(el, compile_context, level)

    def _compile_directive_field(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile ``t-field`` expressions into a python code as a list of
        strings.

        The compiled code will call ``_get_field`` method at rendering time
        using the type of value supplied by the field. This behavior can be
        changed with ``t-options-widget`` or ``t-options={'widget': ...}``.

        The code will contain evaluation and rendering of the compiled value
        from the record field. If the compiled value is None or False,
        the tag is not added to the render
        (Except if the widget forces rendering or there is default content.).
        """
        tagName = el.tag
        if tagName in FORBIDDEN_FIELD_TAGS:
            raise ValueError(
                f"QWeb widgets do not work correctly on {tagName!r} elements"
            )
        if tagName == "t":
            raise ValueError(
                "t-field can not be used on a t element, provide an actual HTML node"
            )
        if "." not in (el.get("t-field") or ""):
            raise ValueError(
                "t-field must have at least a dot like 'record.field_name'"
            )

        return self._compile_directive_out(el, compile_context, level)

    def _compile_directive_call(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Compile `t-call` expressions into a python code as a list of
        strings.

        `t-call` allows formatting strings dynamically at rendering time.
        Can use `t-options` used to call and render the sub-template at
        rendering time.
        The sub-template is called with a copy of the rendering values
        dictionary. The dictionary contains the key 0 coming from the
        compilation of the contents of this element

        The code will contain the call of the template and a function from the
        compilation of the content of this element.
        """
        expr = el.attrib.pop("t-call")

        el_tag = etree.QName(el.tag).localname if el.nsmap else el.tag
        if el_tag != "t":
            raise SyntaxError(
                f"t-call must be on a <t> element (actually on <{el_tag}>)."
            )

        if el.attrib.get("t-call-options"):  # retro-compatibility
            # lxml's _Attrib has no .set() method; assign via item access.
            # el.attrib.set(...) would raise AttributeError on this (latent)
            # retro-compat path.
            el.attrib["t-options"] = el.attrib.pop("t-call-options")

        nsmap = compile_context.get("nsmap")

        code = self._flush_text(compile_context, level, rstrip=el.tag.lower() == "t")
        _ref, path, xml = compile_context["_qweb_error_path_xml"]

        # options
        el.attrib.pop("t-consumed-options", None)
        code.append(
            indent_code("t_call_options = values.pop('__qweb_options__', {})", level)
        )
        if nsmap:
            # update this dict with the current nsmap so that the callee know
            # whether outputting the xmlns attributes is relevant or not
            nsmap = []
            for key, value in compile_context["nsmap"].items():
                if isinstance(key, str):
                    nsmap.append(f"{key!r}:{value!r}")
                else:
                    nsmap.append(f"None:{value!r}")
            code.append(
                indent_code(
                    f"t_call_options.update(nsmap={{{', '.join(nsmap)}}})",
                    level,
                )
            )

        # values from content (t-out="0")
        if bool(list(el) or el.text):
            is_deprecated_version = not any(
                not key.startswith("t-") for key in el.attrib
            ) and any(n.attrib.get("t-set") for n in el)

            def_name = compile_context["make_name"]("t_call")
            code_content = [f"def {def_name}(self, values):"]
            code_content.append(indent_code(self._element_marker(path, xml), 1))
            code_content.extend(
                self._compile_directive(el, compile_context, "inner-content", 1)
            )
            self._append_text(
                "", compile_context
            )  # To ensure the template function is a generator and doesn't become a regular function
            code_content.extend(self._flush_text(compile_context, 1, rstrip=True))

            compile_context["template_functions"][def_name] = code_content

            code.append(
                indent_code(
                    f"""
                t_call_content_values = values.copy()
                qwebContent = QwebContent(self, QwebCallParameters(self.env.context, {compile_context["ref"]!r}, {def_name!r}, t_call_content_values, 'root', 'inner-content', (template_options['ref'], {path!r}, {xml!r})))
                t_call_values = {{ {T_CALL_SLOT}: qwebContent}}
            """,
                    level,
                )
            )

            if is_deprecated_version:
                # force the loading of the content to get values from t-set
                code.append(
                    indent_code(
                        f"""
                    str(qwebContent)
                    new_values = {{k: v for k, v in t_call_content_values.items() if k != {T_CALL_SLOT} and k != '__qweb_attrs__' and values.get(k) is not v}}
                    t_call_values.update(new_values)
                """,
                        level,
                    )
                )
        else:
            code.append(indent_code(f"t_call_values = {{ {T_CALL_SLOT}: '' }}", level))

        # args to values
        for key in list(el.attrib):
            if key.endswith(".f"):
                name = key.removesuffix(".f")
                value = el.attrib.pop(key)
                code.append(
                    indent_code(
                        f"t_call_values[{name!r}] = {self._compile_format(value)}",
                        level,
                    )
                )
            elif key.endswith(".translate"):
                name = key.removesuffix(".translate")
                value = el.attrib.pop(key)
                if self.env.context.get("edit_translations"):
                    code.append(
                        indent_code(
                            f"t_call_values[{name!r}] = Markup({self._compile_format(value)})",
                            level,
                        )
                    )
                else:
                    code.append(
                        indent_code(
                            f"t_call_values[{name!r}] = {self._compile_format(value)}",
                            level,
                        )
                    )
            elif not key.startswith("t-"):
                value = el.attrib.pop(key)
                code.append(
                    indent_code(
                        f"t_call_values[{key!r}] = {self._compile_expr(value)}",
                        level,
                    )
                )
            elif key == "t-args":
                value = el.attrib.pop(key)
                code.append(self._compile_dict_merge("t_call_values", value, level))

        template = expr if expr.isnumeric() else self._compile_format(expr)

        # call
        code.append(
            indent_code(
                f"""
            template = {template}
            """,
                level,
            )
        )
        if "%" in template:
            code.append(
                indent_code(
                    """
                if template.isnumeric():
                    template = int(template)
                """,
                    level,
                )
            )

        code.append(
            indent_code(
                f"yield QwebCallParameters(t_call_options, template, None, t_call_values, True, 't-call', (template_options['ref'], {path!r}, {xml!r}))",
                level,
            )
        )

        return code

    def _compile_directive_lang(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        if "t-call" not in el.attrib:
            msg = "t-lang is an alias of t-options-lang but only available on the same node of t-call"
            raise SyntaxError(msg)
        el.attrib["t-options-lang"] = el.attrib.pop("t-lang")
        return self._compile_node(el, compile_context, level)

    def _compile_directive_call_assets(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        """Aggregate and minify the JS/CSS assets for the ``t-call-assets`` tag."""
        if len(el) > 0:
            msg = "t-call-assets cannot contain children nodes"
            raise SyntaxError(msg)

        code = self._flush_text(compile_context, level)
        xmlid = el.attrib.pop("t-call-assets")
        css = self._compile_bool(el.attrib.pop("t-css", True))
        js = self._compile_bool(el.attrib.pop("t-js", True))
        # async_load support was removed
        defer_load = self._compile_bool(el.attrib.pop("defer_load", False))
        lazy_load = self._compile_bool(el.attrib.pop("lazy_load", False))
        media = el.attrib.pop("media", False)
        autoprefix = self._compile_bool(el.attrib.pop("t-autoprefix", False))
        code.append(
            indent_code(
                f"""
            t_call_assets_nodes = self._get_asset_nodes(
                {xmlid!r},
                css={css},
                js={js},
                debug=values.get("debug"),
                defer_load={defer_load},
                lazy_load={lazy_load},
                media={media!r},
                autoprefix={autoprefix}
            )
        """.strip(),
                level,
            )
        )

        code.append(
            indent_code(
                """
            for index, (tagName, asset_attrs) in enumerate(t_call_assets_nodes):
                if index:
                    yield '\\n        '
                yield '<'
                yield tagName

                # Extract inline text content (import maps, loader shim, bridge
                # scripts) WITHOUT mutating asset_attrs: these node dicts are
                # served straight from the ormcache (_get_native_module_nodes_cached),
                # so a .pop() permanently strips 'text' from the cached copy and
                # every render after the first emits an empty <script>. Read with
                # .get and pass a 'text'-free copy to attribute post-processing.
                text_content = asset_attrs.get("text") if asset_attrs else None
                # Asset nodes are framework-generated static markup (bundle
                # URLs, media/defer attributes): post-process them as static
                # attributes, like the other compile-time static nodes.
                attrs = self._post_processing_att(
                    tagName,
                    {k: v for k, v in asset_attrs.items() if k != "text"}
                    if asset_attrs
                    else {},
                    is_static=True,
                )
                for name, value in attrs.items():
                    if value or isinstance(value, str):
                        yield f' {escape(str(name))}="{escape(str(value))}"'

                if tagName in VOID_ELEMENTS:
                    yield '/>'
                else:
                    yield '>'
                    if text_content:
                        yield str(text_content)
                    yield '</'
                    yield tagName
                    yield '>'
                """,
                level,
            )
        )

        return code

    # methods called by the compiled function at rendering time.

    def _debug_trace(self, debugger: str, values: dict[str, Any]) -> None:
        """Method called at running time to load debugger."""
        if not debugger:
            breakpoint()  # noqa: T100
        elif debugger in SUPPORTED_DEBUGGER:
            warnings.warn(
                "Using t-debug with an explicit debugger is deprecated "
                "since Odoo 17.0, keep the value empty and configure the "
                "``breakpoint`` builtin instead.",
                category=DeprecationWarning,
                stacklevel=2,
            )
            __import__(debugger).set_trace()
        else:
            raise ValueError(f"unsupported t-debug value: {debugger}")

    def _post_processing_att(
        self, tagName: str, atts: dict[str, Any], *, is_static: bool = False
    ) -> dict[str, Any]:
        """Method called at compile time for static nodes and at running time
        for dynamic attributes.

        May be overridden to filter or modify the attributes (during compilation
        for static nodes, or after compilation for dynamic elements).

        :param is_static: ``True`` when called at compile time on the
            attributes of a purely static node (template-author content).
            Dynamic attributes (``is_static=False``) additionally get the
            malicious-scheme scrub below. An explicit keyword rather than an
            in-band ``__is_static_node`` key smuggled through ``atts``: the
            sentinel leaked into the rendered HTML whenever an override
            returned before calling ``super()``.

        :rtype: dict
        """
        if not is_static:
            # Scrub every URL-bearing attribute a browser will navigate/execute
            # from: besides href/src/action/formaction, SVG ``xlink:href`` (e.g.
            # ``<a xlink:href="javascript:…">``) and ``<object data="javascript:…">``
            # also run the scheme, so a bare href/src allow-list leaks XSS.
            for attr in ("href", "src", "action", "formaction", "xlink:href", "data"):
                if (value := atts.get(attr)) and MALICIOUS_SCHEMES(
                    URL_CONTROL_CHARS.sub("", str(value))
                ):
                    atts[attr] = ""
        return atts

    def _get_field(
        self,
        record: models.BaseModel,
        field_name: str,
        expression: str,
        tagName: str,
        field_options: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[dict[str, Any], str | Markup | bool | None, bool]:
        """Method called at rendering time to return the field value.

        :returns: tuple:
            * dict: attributes
            * string or None: content
            * boolean: force_display display the tag if the content and default_content are None
        """
        field = record._fields[field_name]

        # adds generic field options
        field_options["tagName"] = tagName
        field_options["expression"] = expression
        field_options["type"] = field_options.get("widget", field.type)
        inherit_branding = (
            self.env.context["inherit_branding"]
            if "inherit_branding" in self.env.context
            else self.env.context.get("inherit_branding_auto")
            and record.has_access("write")
        )
        field_options["inherit_branding"] = inherit_branding
        translate = (
            self.env.context.get("edit_translations")
            and values.get("translatable")
            and field.translate
        )
        field_options["translate"] = translate

        # field converter
        model = "ir.qweb.field." + field_options["type"]
        converter = self.env[model] if model in self.env else self.env["ir.qweb.field"]

        # get content (the return values from fields are considered to be markup safe)
        content = converter.record_to_html(record, field_name, field_options)
        attributes = converter.attributes(record, field_name, field_options, values)

        return (attributes, content, inherit_branding or translate)

    def _get_widget(
        self,
        value: Any,
        expression: str,
        tagName: str,
        field_options: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[dict[str, Any], str | Markup | bool | None, bool | None]:
        """Method called at rendering time to return the widget value.

        :returns: tuple:
            * dict: attributes
            * string or None: content
            * boolean: force_display display the tag if the content and default_content are None
        """
        widget = field_options.get("widget")
        if not widget:
            # A bare KeyError here was the only feedback for a ``t-options``
            # on a ``t-out``/``t-esc`` without a widget; name the fix instead.
            msg = (
                f"t-options on the t-out/t-esc {expression!r} requires a "
                "'widget' option, e.g. t-options-widget=\"'date'\" or "
                "t-options=\"{'widget': 'date'}\""
            )
            raise ValueError(msg)
        field_options["type"] = widget
        field_options["tagName"] = tagName
        field_options["expression"] = expression
        inherit_branding = self.env.context.get("inherit_branding")
        field_options["inherit_branding"] = inherit_branding

        # field converter
        model = "ir.qweb.field." + field_options["type"]
        converter = self.env[model] if model in self.env else self.env["ir.qweb.field"]

        # get content (the return values from widget are considered to be markup safe)
        content = converter.value_to_html(value, field_options)
        attributes = {}
        attributes["data-oe-type"] = field_options["type"]
        attributes["data-oe-expression"] = field_options["expression"]

        return (attributes, content, inherit_branding)


# ---------------------------------------------------------------------------
# DB-less rendering (``render`` below): a self-contained ``ir.qweb`` that runs
# outside any registry. Widget/field/asset rendering is intentionally absent.
#
# These classes are module-level (defined once) rather than nested in ``render``.
# The nesting was load-bearing only to give each ``render()`` its own fresh
# ormcaches — ``BaseModel`` has ``__slots__`` and a read-only ``pool``, so
# per-call cache state can't live on the instance and a shared class attribute
# would leak across renders. We keep that guarantee by threading a throwaway
# ``_MockRegistry`` through ``env`` instead.


class _MockCursor:
    def __init__(self) -> None:
        self.cache: dict[str, Any] = {}


class _MockRegistry:
    """A throwaway registry holding the ormcaches for a single DB-less render.

    ``ir.qweb``'s compile path is ormcached on ``self.pool._Registry__caches``;
    a fresh registry per ``render()`` keeps those caches from leaking across
    unrelated standalone renders (the caller's ``load`` may return a different
    tree for the same ref on a later call).
    """

    db_name = None

    def __init__(self) -> None:
        caches = {
            cache_name: LRU(cache_size)
            for cache_name, cache_size in _REGISTRY_CACHES.items()
        }
        self._Registry__caches = caches
        self._Registry__caches_groups = _group_caches_by_prefix(caches)


class _MockEnv(dict):
    """Minimal stand-in for ``api.Environment`` used by DB-less rendering.

    Carries the per-render ``registry`` and re-threads it on every clone so that
    ``with_context`` / ``with_env`` (which rebuild the environment) keep sharing
    one set of ormcaches for the duration of a single ``render()``.
    """

    def __init__(
        self,
        registry: _MockRegistry | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.registry = registry if registry is not None else _MockRegistry()
        self.context: dict[str, Any] = {} if context is None else dict(context)
        self.cr = _MockCursor()

    def __call__(
        self,
        cr: Any = None,
        user: Any = None,
        context: dict[str, Any] | None = None,
        su: Any = None,
    ) -> _MockEnv:
        """Return a cloned environment (optionally with a new context), keeping
        the same per-render registry. Lets ``ir_qweb.with_context`` work on the
        sandboxed qweb.
        """
        return _MockEnv(
            registry=self.registry,
            context=self.context if context is None else context,
        )


class _MockIrQWeb(IrQweb):
    _register = False  # not visible in real registry

    @property
    def pool(self) -> _MockRegistry:
        # Same object as ``env.registry`` — matches real ``BaseModel.pool``
        # semantics — so the per-render ormcaches are reachable by ``@ormcache``.
        return self.env.registry

    def _get_template_info(self, id_or_xmlid: int | str) -> dict[str, Any]:
        return defaultdict(lambda: None, id=id_or_xmlid)

    def _preload_trees(
        self, refs: Sequence[int | str]
    ) -> dict[int | str, dict[str, Any]]:
        values = {}
        for ref in refs:
            tree, vid = self.env.context["load"](ref)
            values[ref] = values[vid] = {
                "tree": tree,
                "template": etree.tostring(tree, encoding="unicode"),
                "xmlid": vid,
                "ref": None,
            }
        return values

    def _prepare_environment(self, values: dict[str, Any]) -> Self:
        values["true"] = True
        values["false"] = False
        return self.with_context(__qweb_loaded_functions={})

    def _get_field(self, *args: Any) -> None:
        msg = "Fields are not allowed in this rendering mode. Please use \"env['ir.qweb']._render\" method"
        raise NotImplementedError(msg)

    def _get_widget(self, *args: Any) -> None:
        msg = "Widgets are not allowed in this rendering mode. Please use \"env['ir.qweb']._render\" method"
        raise NotImplementedError(msg)

    def _get_asset_nodes(self, *args: Any) -> None:
        msg = "Assets are not allowed in this rendering mode. Please use \"env['ir.qweb']._render\" method"
        raise NotImplementedError(msg)


def render(
    template_name: str | int, values: dict[str, Any], load: Any, **options: Any
) -> Markup:
    """Rendering of a qweb template without database and outside the registry.
    (Widget, field, or asset rendering is not implemented.)
    :param (string|int) template_name: template identifier
    :param dict values: template values to be used for rendering
    :param def load: function like `load(template_name)` which returns an etree
        from the given template name (from initial rendering or template
        `t-call`).
    :param options: used to compile the template
    :return: the rendered template, markup-safe
    :rtype: markupsafe.Markup
    """
    renderer = _MockIrQWeb(_MockEnv(), (), ())
    return renderer._render(
        template_name, values, load=load, minimal_qcontext=True, **options
    )
