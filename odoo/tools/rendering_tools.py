import functools
import numbers
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode

from dateutil import relativedelta
from lxml import etree, html
from markupsafe import Markup, escape

from odoo.tools import safe_eval

# The default clause tolerates ``\}`` and ``\\`` so that a default value may
# contain the ``}}`` that would otherwise terminate the placeholder. Any other
# backslash -- ``C:\temp`` -- is matched by the bare ``.`` alternative and left
# alone, so templates written before the escape existed parse unchanged.
INLINE_TEMPLATE_REGEX = re.compile(
    r"\{\{(.+?)(?:\|\|\|\s*((?:\\[\\}]|.)*?))?\}\}", re.DOTALL
)
INLINE_DEFAULT_ESCAPE_RE = re.compile(r"\\([\\}])")


def unescape_inline_default(default: str) -> str:
    """Undo the escaping :data:`INLINE_TEMPLATE_REGEX` tolerates in a default."""
    return INLINE_DEFAULT_ESCAPE_RE.sub(r"\1", default)


def _template_hasattr(obj: object, name: str) -> bool:
    if name.startswith("__") and name.endswith("__"):
        return False
    return hasattr(obj, name)


template_env_globals = {
    "str": str,
    "quote": lambda s, safe="/:": quote(str(s), safe=safe),
    "urlencode": urlencode,
    "datetime": safe_eval.datetime,
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "filter": filter,
    "reduce": functools.reduce,
    "map": map,
    "relativedelta": relativedelta.relativedelta,
    "round": round,
    "hasattr": _template_hasattr,
}


def parse_inline_template(text: str) -> list[tuple[str, str, str]]:
    groups: list[tuple[str, str, str]] = []
    current_literal_index = 0
    for match in INLINE_TEMPLATE_REGEX.finditer(text):
        literal = text[current_literal_index : match.start()]
        expression = match.group(1)
        default = match.group(2)
        groups.append(
            (literal, expression.strip(), unescape_inline_default(default or ""))
        )
        current_literal_index = match.end()

    literal = text[current_literal_index:]
    if literal:
        groups.append((literal, "", ""))

    return groups


def convert_inline_template_to_qweb(template: str | None) -> Markup:
    template_instructions = parse_inline_template(template or "")
    preview_markup = []
    for string, expression, default in template_instructions:
        if expression:
            preview_markup.append(
                Markup('{}<t t-out="{}">{}</t>').format(string, expression, default)
            )
        else:
            preview_markup.append(string)
    return Markup("").join(preview_markup)


#: Values with no text form. ``str`` answers ``b'iVBORw0KGgo...'`` for these --
#: the whole base64 payload and the Python repr around it -- so a placeholder
#: that resolves to one renders its default instead. psycopg hands back
#: ``memoryview`` for some bytea reads, hence the full triple.
BINARY_TYPES = (bytes, bytearray, memoryview)


def renders_as_no_value(result: object) -> bool:
    if isinstance(result, bool):
        return not result
    if isinstance(result, BINARY_TYPES):
        return True
    return not result and not isinstance(result, numbers.Number)


def render_inline_template(
    template_instructions: list[tuple[str, str, str]],
    variables: dict[str, object],
    format_value: Callable[[object], str] = str,
) -> str:
    """Evaluate an inline template.

    ``format_value`` turns a resolved value into text. It exists so that the caller
    — mail, the only consumer — can render a recordset the same way its
    evaluation-free renderer does; ``str`` alone answers ``res.partner(11,)``.
    """
    results = []
    for string, expression, default in template_instructions:
        results.append(string)

        if expression:
            result = safe_eval.safe_eval(expression, variables)
            if renders_as_no_value(result):
                result = default
            if result != "":
                results.append(format_value(result))

    return "".join(results)


class QWebErrorInfo:
    def __init__(
        self,
        error: str,
        ref_name: str | int | None,
        ref: int | None,
        path: str | None,
        element: str | None,
        source: list[tuple[int | str, str, str]],
        surrounding: str,
    ) -> None:
        self.error = error
        self.template = ref_name
        self.ref = ref
        self.path = path
        self.element = element
        self.source = source
        self.surrounding = surrounding

    def __str__(self) -> str:
        info = [self.error]
        if self.template is not None:
            info.append(f"Template: {self.template}")
        if self.ref is not None:
            info.append(f"Reference: {self.ref}")
        if self.path is not None:
            info.append(f"Path: {self.path}")
        if self.element is not None:
            info.append(f"Element: {self.element}")
        if self.source:
            source = "\n          ".join(str(v) for v in self.source)
            info.append(f"From: {source}")
        if self.surrounding:
            info.append(f"QWeb generated code:\n{self.surrounding}")
        return "\n    ".join(info)


class QWebError(Exception):
    def __init__(self, qweb: QWebErrorInfo) -> None:
        super().__init__("Error while rendering the template")
        self.qweb = qweb

    def __str__(self) -> str:
        return f"{super().__str__()}:\n    {self.qweb}"


# ---------------------------------------------------------------------------
# The evaluation-free QWeb renderer
#
# `mail` renders a `t-out` body one of two ways: through `ir.qweb`, which
# compiles the template to Python, or -- when every expression in it is
# allow-listed -- by substituting values into literal text, with no evaluator
# involved at all. What follows is the half of that second renderer which is a
# function of a tree and a value: no cursor, no registry, no model, so it is
# unit-testable without any of them. `mail` owns the half that resolves an
# expression against a record.
# ---------------------------------------------------------------------------


class StaticRenderUnsupported(Exception):
    """This template needs an evaluator, so the caller must fall back to QWeb."""


#: Elements HTML serialises without a closing tag. Everything else is emitted as
#: `<p></p>` rather than `<p/>`, which is what `ir.qweb` writes -- the two
#: renderers must not disagree about a template's bytes.
VOID_HTML_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

#: Where a value goes in the serialised body. Private Use codepoints, because
#: the marker has to survive serialisation as text and mean nothing to HTML.
#: They are not rare in a mail body -- U+E000 is the first glyph of most icon
#: fonts -- so :func:`compile_static_template` checks that the markers it reads
#: back are the ones it wrote.
HOLE_OPEN, HOLE_CLOSE = "\ue000", "\ue001"
HOLE_RE = re.compile(f"{HOLE_OPEN}(\\d+){HOLE_CLOSE}")


def escape_static_text(text: str) -> str:
    """Escape a literal for HTML text content, the way lxml serialises it.

    Quotes are left alone on purpose: this escapes an element's *body*, where a
    quote needs no escaping and `ir.qweb` emits none either.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def serialize_static_tree(tree: etree._Element) -> Markup:
    """Serialise a parsed body the way `ir.qweb` serialises the same one."""
    for element in tree.iter():
        if (
            isinstance(element.tag, str)
            and element.text is None
            and len(element) == 0
            and element.tag.lower() not in VOID_HTML_ELEMENTS
        ):
            element.text = ""
    body = html.tostring(tree, encoding="unicode", method="xml")
    return Markup(body.removeprefix("<div>").removesuffix("</div>"))


def compile_static_template(
    tree: etree._Element,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Turn a parsed body into literal segments and the holes between them.

    Returns ``(segments, holes)`` with ``len(segments) == len(holes) + 1``: the
    text before each value, and each value's ``(expression, default)``.

    The tree is consumed -- pass a copy.
    """
    holes: list[tuple[str, str]] = []
    for element in list(tree.iter()):
        if not isinstance(element.tag, str) or element.get("t-out") is None:
            continue
        expression = element.get("t-out").strip()
        del element.attrib["t-out"]
        default = escape_static_text((element.text or "").strip())
        holes.append((expression, default))
        element.text = f"{HOLE_OPEN}{len(holes) - 1}{HOLE_CLOSE}"
        if element.tag.lower() == "t":
            element.drop_tag()

    segments = HOLE_RE.split(str(serialize_static_tree(tree)))
    # The markers were written in document order, one per hole, so the indices
    # read back must be 0, 1, 2, ... Anything else means the body's own text
    # carried a marker, and substituting into it would either overwrite the
    # author's literal text or index a hole that does not exist.
    if [int(index) for index in segments[1::2]] != list(range(len(holes))):
        raise StaticRenderUnsupported(
            "the template's own text carries this renderer's hole markers"
        )
    return segments[::2], holes


def render_static_program(
    segments: list[str],
    holes: list[tuple[str, str]],
    resolve: Callable[[str], Any],
) -> Markup:
    """Fill a compiled program's holes.

    ``resolve`` answers one expression. None and False mean "no value", which is
    the same test `ir.qweb`'s `_compile_out_emit` makes before it writes an
    element's default body instead.
    """
    out = [segments[0]]
    for (expression, default), segment in zip(holes, segments[1:], strict=True):
        value = resolve(expression)
        if value is None or value is False:
            out.append(default)
        elif isinstance(value, Markup):
            out.append(str(value))
        else:
            out.append(str(escape(str(value))))
        out.append(segment)
    return Markup("".join(out))
