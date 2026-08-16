"""Sphinx info-field docstrings and Python signatures, as data.

Two jobs, both Odoo-free (docutils and the standard library are the only
dependencies):

* parse the *vocabulary* of Sphinx info fields -- ``:param:``, ``:raises:``,
  ``:rtype:`` and their aliases -- out of a docstring, and render the prose
  around them to HTML;
* reflect a callable's signature into a JSON-serialisable :class:`Signature`,
  merging in whatever the docstring documented.

The vocabulary is shared on purpose: ``addons/test_lint`` *lints* these fields
and ``addons/api_doc`` *renders* them, and two copies of the table drift.

Annotations are read with :data:`annotationlib.Format.STRING` (PEP 649), so a
signature whose annotations name types imported under ``if TYPE_CHECKING:``
reflects fine instead of raising ``NameError`` -- which is most of the ORM.
That is also what keeps this module Odoo-free: nothing here has to *resolve* a
type, only carry the text of it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import inspect
import io
import json
import logging
import typing
from annotationlib import Format

import docutils.core
from docutils import parsers, readers, writers
from docutils.writers.html4css1 import Writer as HtmlWriter

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from docutils import nodes

__all__ = [
    "PARSE_ERROR",
    "RST_INFO_FIELDS",
    "InfoField",
    "Param",
    "Return",
    "Signature",
    "iter_info_fields",
    "parse_signature",
    "render_children_html",
    "render_docstring",
    "render_html",
    "stringify_annotation",
    "to_doctree",
]

_logger = logging.getLogger(__name__)

EMPTY: typing.Final = inspect.Parameter.empty

#: Sphinx info-field names, mapped to the canonical kind they denote.
#: https://www.sphinx-doc.org/en/master/usage/domains/python.html#info-field-lists
RST_INFO_FIELDS: typing.Final[dict[str, str]] = {
    "param": "param",
    "parameter": "param",
    "arg": "param",
    "argument": "param",
    "key": "param",
    "keyword": "param",
    "type": "type",
    "raises": "raises",
    "raise": "raises",
    "except": "raises",
    "exception": "raises",
    "var": "var",
    "ivar": "var",
    "cvar": "var",
    "vartype": "vartype",
    "returns": "returns",
    "return": "returns",
    "rtype": "rtype",
    "meta": "meta",
}

#: Info-field kinds that describe an attribute rather than the call, plus the
#: no-op ``:meta:``. Recognised so a caller can skip them deliberately instead
#: of reporting them as unparsable.
NON_CALL_FIELDS: typing.Final[frozenset[str]] = frozenset({"var", "vartype", "meta"})

PARSE_ERROR: typing.Final = '''\
Unable to parse the docstring as reStructuredText.
Want to help fix the docstrings? Check out the test_docstring linter!
"""
{}
"""
{}'''

# report_level 3 keeps docutils quiet below ERROR; halt_level 5 means it never
# raises on our behalf. raw/file_insertion are disabled because a docstring is
# untrusted input as far as this module is concerned: neither `.. raw:: html`
# nor `.. include::` may reach the renderer.
_SAFE_SETTINGS: typing.Final[dict[str, typing.Any]] = {
    "report_level": 3,
    "halt_level": 5,
    "raw_enabled": False,
    "file_insertion_enabled": False,
}


def _make_settings(
    writer_name: str, overrides: dict[str, typing.Any]
) -> typing.Any:  # docutils returns an optparse Values
    parser = parsers.get_parser_class("restructuredtext")()
    reader = readers.get_reader_class("standalone")(parser)
    writer = writers.get_writer_class(writer_name)()
    publisher = docutils.core.Publisher(reader=reader, parser=parser, writer=writer)
    publisher.process_programmatic_settings(None, overrides, None)
    return publisher.settings


@functools.cache
def _tree_settings() -> typing.Any:
    return _make_settings("pseudoxml", dict(_SAFE_SETTINGS))


@functools.cache
def _html_settings() -> typing.Any:
    return _make_settings("html", {**_SAFE_SETTINGS, "embed_stylesheet": False})


@functools.cache
def _empty_root() -> Callable[[], nodes.document]:
    """A factory for blank docutils documents to hang a subtree under."""
    return docutils.core.publish_doctree("").copy


def to_doctree(docstring: str) -> nodes.document:
    """Parse *docstring* as reStructuredText, logging any docutils complaint."""
    with contextlib.redirect_stderr(io.StringIO()) as stderr:
        doctree = docutils.core.publish_doctree(docstring, settings=_tree_settings())
        if stderr.tell():
            _logger.warning(PARSE_ERROR.format(docstring, stderr.getvalue()))
        return doctree


def render_html(tree: nodes.Node) -> str:
    """Render a doctree (or one node of one) to an HTML fragment."""
    root = _empty_root()()
    root.append(tree)
    html = docutils.core.publish_from_doctree(
        root, writer=HtmlWriter(), settings=_html_settings()
    )
    head = b'\n</head>\n<body>\n<div class="document">'
    tail = b"</div>\n</body>\n</html>\n"
    return html.partition(head)[2].removesuffix(tail).strip().decode()


def render_children_html(tree: nodes.Element) -> str:
    return "".join(render_html(child) for child in tree.children)


class InfoField(typing.NamedTuple):
    """One ``:kind [annotation] name: body`` entry of a docstring."""

    kind: str | None  # canonical kind, None when the name is not a known field
    name: str  # what followed the kind, verbatim and stripped
    body: nodes.Element
    raw: str  # the field name as written, for error messages


def iter_info_fields(doctree: nodes.document) -> Iterator[InfoField]:
    """Yield every info field of *doctree*, removing their lists from it.

    The removal is the point: what is left of the tree afterwards is the prose,
    ready to be rendered on its own.
    """
    field_lists = [
        node for node in doctree if node.tagname in ("docinfo", "field_list")
    ]
    for field_list in field_lists:
        for field in field_list:
            field_name, field_body = field.children
            raw = str(field_name[0])
            kind, _, name = raw.partition(" ")
            yield InfoField(RST_INFO_FIELDS.get(kind), name.strip(), field_body, raw)
        doctree.remove(field_list)


def stringify_annotation(annotation: typing.Any) -> str | None:
    """Render an annotation as source-like text, or None when there is none."""
    if annotation is EMPTY:
        return None
    if isinstance(annotation, str):
        return annotation
    if hasattr(annotation, "__origin__"):
        return str(annotation)
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


ParamKind = typing.Literal[
    # def f(pos_only, /, pos_or_kw, *var_pos, kw_only, **var_kw)
    "POSITIONAL_ONLY",
    "POSITIONAL_OR_KEYWORD",
    "VAR_POSITIONAL",
    "KEYWORD_ONLY",
    "VAR_KEYWORD",
]
"""The five ``inspect._ParameterKind`` member names.

Named rather than written inline in :class:`Param` so ``from_inspect`` can spell
the same type in its cast: ``inspect.Parameter.kind.name`` is typed ``str``, and
only the enum guarantees that string is one of these five.
"""


@dataclasses.dataclass(slots=True)
class Param:
    """One parameter of a :class:`Signature`.

    ``slots=True`` is load-bearing: it turns a typo in an attribute name into
    an ``AttributeError`` instead of a silently created attribute that
    ``as_dict`` would then export under the wrong key.
    """

    name: str
    kind: ParamKind
    default: typing.Any
    annotation: str | None
    doc: str | None

    @classmethod
    def from_inspect(cls, parameter: inspect.Parameter) -> Param:
        return cls(
            name=parameter.name,
            kind=typing.cast("ParamKind", parameter.kind.name),
            default=parameter.default,
            annotation=stringify_annotation(parameter.annotation),
            doc=None,
        )

    def as_dict(self) -> dict[str, typing.Any]:
        d: dict[str, typing.Any] = {
            "name": self.name,
            "kind": self.kind,
            "default": self.default,
            "annotation": self.annotation,
            "doc": self.doc,
        }
        if self.kind == "POSITIONAL_OR_KEYWORD":
            # most (99%) params are POSITIONAL_OR_KEYWORD: make the export
            # smaller by leaving those implicit
            del d["kind"]
        if self.annotation is None:
            del d["annotation"]
        if self.doc is None:
            del d["doc"]
        if self.default is EMPTY:
            del d["default"]
        else:
            # a default that cannot survive the trip is worse than no default
            try:
                json.dumps(self.default)
            except TypeError, ValueError:
                del d["default"]
        return d


@dataclasses.dataclass(slots=True)
class Return:
    annotation: str | None
    doc: str | None

    @classmethod
    def from_inspect(cls, return_annotation: typing.Any) -> Return:
        return cls(stringify_annotation(return_annotation), doc=None)

    def as_dict(self) -> dict[str, typing.Any]:
        d: dict[str, typing.Any] = {}
        if self.annotation is not None:
            d["annotation"] = self.annotation
        if self.doc is not None:
            d["doc"] = self.doc
        return d


@dataclasses.dataclass(slots=True)
class Signature:
    parameters: dict[str, Param]
    return_: Return
    api: list[str]
    raise_: dict[str, str]
    doc: str | None

    def as_dict(self) -> dict[str, typing.Any]:
        d: dict[str, typing.Any] = {
            "signature": self.stringify(annotation=False),
            "parameters": {
                (p := param.as_dict()).pop("name"): p
                for param in self.parameters.values()
            },
        }
        if return_dict := self.return_.as_dict():
            d["return"] = return_dict
        if self.api:
            d["api"] = self.api
        if self.raise_:
            d["raise"] = self.raise_
        if self.doc is not None:
            d["doc"] = self.doc
        return d

    def stringify(
        self,
        annotation: bool = True,
        default: bool = True,
        return_annotation: bool = True,
    ) -> str:
        """Render the signature the way it would be written in Python.

        The markers matter as much as the names: a reader copying
        ``(field_name, kwargs)`` writes a call that cannot work, where
        ``(field_name, **kwargs)`` tells them what to send.
        """
        rendered: list[str] = []
        previous: str | None = None
        starred = False
        for name, param in self.parameters.items():
            if previous == "POSITIONAL_ONLY" and param.kind != "POSITIONAL_ONLY":
                rendered.append("/")
            if param.kind == "VAR_POSITIONAL":
                starred = True
            elif param.kind == "KEYWORD_ONLY" and not starred:
                rendered.append("*")
                starred = True

            text = name
            if param.kind == "VAR_POSITIONAL":
                text = f"*{name}"
            elif param.kind == "VAR_KEYWORD":
                text = f"**{name}"
            if annotation and param.annotation:
                text += f": {param.annotation}"
                if default and param.default is not EMPTY:
                    text += f" = {param.default!r}"
            elif default and param.default is not EMPTY:
                text += f"={param.default!r}"
            rendered.append(text)
            previous = param.kind
        if previous == "POSITIONAL_ONLY":
            rendered.append("/")

        out = f"({', '.join(rendered)})"
        if return_annotation and self.return_.annotation:
            out += f" -> {self.return_.annotation}"
        return out


def render_docstring(text: str) -> str:
    """Render a whole docstring to HTML, info fields and all."""
    return render_html(to_doctree(inspect.cleandoc(text)))


def parse_signature(
    method: Callable[..., typing.Any],
    *,
    docstring: str | None = None,
    normalize_return: Callable[[str | None], str | None] | None = None,
) -> Signature:
    """Reflect *method* into a :class:`Signature`, docstring included.

    :param method: any callable; ``self``/``cls`` is dropped when present
    :param docstring: documentation to merge in, when it does not live on
        *method* itself -- an override that documents nothing should still be
        described by the docstring of the implementation it replaced
    :param normalize_return: optional hook rewriting the return annotation,
        for callers whose transport does not return what the annotation says
        (Odoo's RPC returns ids where the signature says a recordset)
    :return: the parsed signature
    """
    isign = inspect.signature(method, annotation_format=Format.STRING)

    # strip self and cls: the caller of an RPC method does not pass them
    parameters = list(isign.parameters.values())
    if parameters and parameters[0].name in ("self", "cls"):
        isign = isign.replace(parameters=parameters[1:])

    return_annotation = stringify_annotation(isign.return_annotation)
    if normalize_return is not None:
        return_annotation = normalize_return(return_annotation)

    signature = Signature(
        parameters={
            param_name: Param.from_inspect(param)
            for param_name, param in isign.parameters.items()
        },
        return_=Return(return_annotation, doc=None),
        api=[],
        raise_={},
        doc=None,
    )

    if documentation := (docstring if docstring is not None else method.__doc__):
        enhance_signature_using_docstring(signature, documentation)

    return signature


def enhance_signature_using_docstring(signature: Signature, docstring: str) -> None:
    """Fold a docstring's info fields into *signature*, in place."""
    doctree = to_doctree(inspect.cleandoc(docstring))

    for field in iter_info_fields(doctree):
        match (field.kind, field.name):
            # unknown field name (:foo:) -- say so, it is likely a typo
            case (None, _):
                _logger.warning(
                    PARSE_ERROR.format(docstring, f"cannot parse {field.raw}")
                )
            # :var:/:vartype:/:meta: describe something other than the call
            case (kind, _) if kind in NON_CALL_FIELDS:
                pass
            # :param <annotation> <name>: <rst>
            case ("param", annotated_name) if " " in annotated_name:
                annotation, _, name = annotated_name.rpartition(" ")
                if param := signature.parameters.get(name.strip()):
                    if not param.annotation:
                        param.annotation = annotation.strip()
                    param.doc = render_children_html(field.body)
            # :param <name>: <rst>
            case ("param", name):
                if param := signature.parameters.get(name):
                    param.doc = render_children_html(field.body)
            # :type <name>: <annotation>
            case ("type", name):
                if (param := signature.parameters.get(name)) and not param.annotation:
                    param.annotation = field.body.children[0].astext().strip()
            # :returns: <rst>
            case ("returns", ""):
                signature.return_.doc = render_children_html(field.body)
            # :rtype: <annotation>
            case ("rtype", ""):
                if not signature.return_.annotation:
                    signature.return_.annotation = (
                        field.body.children[0].astext().strip()
                    )
            # :raises <exception>: <rst>
            case ("raises", exception):
                signature.raise_[exception] = render_children_html(field.body)
            case _:
                _logger.warning(
                    PARSE_ERROR.format(docstring, f"cannot parse {field.raw}")
                )

    signature.doc = render_html(doctree)
