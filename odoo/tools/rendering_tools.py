import functools
import numbers
import re
from urllib.parse import quote, urlencode

from dateutil import relativedelta
from markupsafe import Markup

from odoo.tools import safe_eval

INLINE_TEMPLATE_REGEX = re.compile(r"\{\{(.+?)(\|\|\|\s*(.*?))?\}\}", re.DOTALL)


def _template_hasattr(obj: object, name: str) -> bool:
    """``hasattr`` that refuses dunder names, matching safe_eval's policy.

    ``safe_eval`` withholds ``getattr`` and rejects dunder names appearing in
    the expression source (``assert_no_dunder_name``), but a *constant* passed
    to ``hasattr`` is not source-level name access, so
    ``hasattr(x, "__globals__")`` answered — a one-bit probe of exactly the
    attributes the surrounding policy exists to hide. It cannot retrieve a
    value, so this closes an inconsistency rather than an escalation.

    Ordinary field probes, which is what templates actually use
    (``hasattr(object, 'website_id')``), are unaffected.
    """
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
        default = match.group(3)
        groups.append((literal, expression.strip(), default or ""))
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


def renders_as_no_value(result: object) -> bool:
    """Whether a rendered expression result means "nothing to render", and so
    falls back to the ``|||`` default.

    Mirrors QWeb's ``t-out`` contract — see ``IrQWeb._compile_directive_out``:
    *"If the compiled value is None or False, the tag is not added to the
    render (except [...] if there is default content)"* — which is the engine
    ``convert_inline_template_to_qweb`` compiles ``{{ expr ||| default }}``
    down to, so the three rendering engines must agree.

    ``False`` is the ORM's marker for every unset non-numeric field and an
    empty recordset is its marker for an unset relation; stringifying those
    would emit the literal ``"False"`` / ``"res.partner()"`` into a subject,
    body or lang. Numeric zeros are genuine values that must render as ``0``:
    they are tested separately because ``False == 0`` and ``bool`` subclasses
    ``int``, so no plain truthiness test can tell them apart.
    """
    if isinstance(result, bool):
        return not result
    return not result and not isinstance(result, numbers.Number)


def render_inline_template(
    template_instructions: list[tuple[str, str, str]], variables: dict[str, object]
) -> str:
    results = []
    for string, expression, default in template_instructions:
        results.append(string)

        if expression:
            result = safe_eval.safe_eval(expression, variables)
            if renders_as_no_value(result):
                result = default
            if result != "":
                results.append(str(result))

    return "".join(results)


class QWebErrorInfo:
    """Structured context for QWeb rendering errors."""

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
    """Exception wrapping a QWebErrorInfo with rendering context."""

    def __init__(self, qweb: QWebErrorInfo) -> None:
        super().__init__("Error while rendering the template")
        self.qweb = qweb

    def __str__(self) -> str:
        return f"{super().__str__()}:\n    {self.qweb}"
