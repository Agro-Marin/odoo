import codecs
import csv
import fnmatch
import functools
import inspect
import io
import json
import locale
import logging
import os
import re
import tarfile
import typing
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from tokenize import DEDENT, INDENT, NEWLINE, STRING, generate_tokens
from types import FrameType
from typing import IO, Any

import polib
from babel.messages import extract
from lxml import etree, html
from markupsafe import Markup, escape
from psycopg.types.json import Json

import odoo
import odoo.release
from odoo.exceptions import UserError
from odoo.libs.collections import OrderedSet, ReadonlyDict

import odoo.addons
from .config import config
from .files import file_open, file_path
from .i18n import format_list
from .locale_utils import get_iso_codes
from .misc import SKIPPED_ELEMENT_TYPES

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.db import BaseCursor

__all__ = [
    "LazyTranslate",
    "_",
    "html_translate",
    "xml_translate",
]

_logger = logging.getLogger(__name__)

PYTHON_TRANSLATION_COMMENT = "odoo-python"

JAVASCRIPT_TRANSLATION_COMMENT = "odoo-javascript"

SKIPPED_ELEMENTS = ("script", "style", "title")

TRANSLATED_ELEMENTS = {
    "abbr",
    "b",
    "bdi",
    "bdo",
    "br",
    "cite",
    "code",
    "data",
    "del",
    "dfn",
    "em",
    "font",
    "i",
    "ins",
    "kbd",
    "keygen",
    "mark",
    "math",
    "meter",
    "output",
    "progress",
    "q",
    "ruby",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "time",
    "u",
    "var",
    "wbr",
    "text",
    "select",
    "option",
}

TRANSLATED_ATTRS = {
    "string",
    "add-label",
    "help",
    "sum",
    "avg",
    "confirm",
    "placeholder",
    "alt",
    "title",
    "aria-label",
    "aria-keyshortcuts",
    "aria-placeholder",
    "aria-roledescription",
    "aria-valuetext",
    "value_label",
    "data-tooltip",
    "label",
    "confirm-label",
    "confirm-title",
    "cancel-label",
}

TRANSLATED_ATTRS.update({f"t-attf-{attr}" for attr in TRANSLATED_ATTRS})

FIELD_TRANSLATE = {
    None: False,
    "standard": True,
}


def is_translatable_attrib(key: str | None, node: etree._Element) -> bool:
    if not key:
        return False
    if "t-call" not in node.attrib and key in TRANSLATED_ATTRS:
        return True
    return key.endswith(".translate")


def is_translatable_attrib_value(node: etree._Element) -> bool:
    classes = node.attrib.get("class", "").split(" ")
    return (
        (node.tag == "input" and node.attrib.get("type", "text") == "text")
        and "datetimepicker-input" not in classes
    ) or (
        (node.tag == "input" and node.attrib.get("type") == "hidden")
        and "o_translatable_input_hidden" in classes
    )


def is_translatable_attrib_text(node: etree._Element) -> bool:
    return node.tag == "field" and node.attrib.get("widget", "") == "url"


OWL_TRANSLATED_ATTRS = {
    "alt",
    "aria-label",
    "aria-placeholder",
    "aria-roledescription",
    "aria-valuetext",
    "data-tooltip",
    "label",
    "placeholder",
    "title",
}

avoid_pattern = re.compile(r"\s*<!DOCTYPE", re.IGNORECASE | re.MULTILINE | re.UNICODE)
space_pattern = re.compile(r"[\s\uFEFF]*")

FORMAT_REGEX = re.compile(r"(?:#\{(.+?)\})|(?:\{\{(.+?)\}\})")


def translate_format_string_expression(
    term: str, callback: Callable[[str], str | None]
) -> str | None:
    expressions: dict[str, str] = {}

    def add(exp_py):
        index = len(expressions)
        expressions[str(index)] = exp_py
        return "{{%s}}" % index

    term_without_py = FORMAT_REGEX.sub(lambda g: add(g.group(0)), term)
    translated_value = callback(term_without_py)
    if translated_value:
        return FORMAT_REGEX.sub(
            lambda g: expressions.get(g.group(0)[2:-2], "None"),
            translated_value,
        )
    return None


def translate_xml_node(
    node: etree._Element,
    callback: Callable[[str], str | None],
    serialize: Callable[[etree._Element], str],
) -> etree._Element:
    """Walk ``node``, handing each translatable run of markup to ``callback``.

    The round-trip of a translated fragment is re-parsed with ``parse_html``,
    deliberately and for both dialects: translators write ``<br>``, which is
    legal HTML and not well-formed XML, so parsing the result strictly would
    turn an ordinary translation into an ``XMLSyntaxError``. This used to take a
    ``parse`` argument that all three call sites supplied and the body never
    read -- an unused parameter that invited exactly the "fix" that breaks it.
    """

    def nonspace(text):
        return bool(text) and not space_pattern.fullmatch(text)

    def is_force_inline(node):
        return "o_translate_inline" in node.attrib.get("class", "").split()

    def translatable(node, force_inline=False):
        force_inline = force_inline or is_force_inline(node)
        return (
            (force_inline or node.tag in TRANSLATED_ELEMENTS)
            and not any(
                key.startswith("t-") or key == "groups" or key.endswith(".translate")
                for key in node.attrib
            )
            and all(translatable(child, force_inline) for child in node)
        )

    def hastext(node, pos=0, force_inline=False):
        force_inline = force_inline or is_force_inline(node)
        while True:
            if nonspace(node[pos - 1].tail if pos else node.text):
                return True
            if pos >= len(node) or not translatable(node[pos], force_inline):
                return False
            child = node[pos]
            if any(
                val
                and (
                    is_translatable_attrib(key, node)
                    or (key == "value" and is_translatable_attrib_value(child))
                    or (key == "text" and is_translatable_attrib_text(child))
                )
                for key, val in child.attrib.items()
            ) or hastext(child, 0, force_inline):
                return True
            pos += 1

    def process(node):
        if (
            isinstance(node, SKIPPED_ELEMENT_TYPES)
            or node.tag in SKIPPED_ELEMENTS
            or node.get("t-translation", "").strip() == "off"
            or (
                node.tag == "attribute"
                and node.get("name") not in ("value", "text")
                and not is_translatable_attrib(node.get("name"), node)
            )
            or (node.getparent() is None and avoid_pattern.match(node.text or ""))
        ):
            return

        pos = 0
        while True:
            if hastext(node, pos):
                div = etree.Element("div")
                div.text = (node[pos - 1].tail if pos else node.text) or ""
                while pos < len(node) and translatable(
                    node[pos], is_force_inline(node)
                ):
                    div.append(node[pos])

                content = serialize(div)[5:-6]
                original = content.strip()
                translated = callback(original)
                if translated:
                    result = content.replace(original, translated)
                    result_elem = parse_html(f"<div>{result}</div>")
                    result_elem.tag = "span"
                    if translatable(result_elem) and hastext(result_elem):
                        div = result_elem
                        if pos:
                            node[pos - 1].tail = div.text
                        else:
                            node.text = div.text

                while len(div) > 0:
                    node.insert(pos, div[0])
                    pos += 1

            if pos >= len(node):
                break

            process(node[pos])
            pos += 1

        for key, val in node.attrib.items():
            if nonspace(val):
                if (
                    is_translatable_attrib(key, node)
                    or (key == "value" and is_translatable_attrib_value(node))
                    or (key == "text" and is_translatable_attrib_text(node))
                ):
                    if key.startswith("t-"):
                        value = translate_format_string_expression(
                            val.strip(), callback
                        )
                    else:
                        value = callback(val.strip())
                    node.set(key, value or val)

    process(node)

    return node


def parse_xml(text: str | bytes) -> etree._Element:
    return etree.fromstring(text)


def serialize_xml(node: etree._Element) -> str:
    return etree.tostring(node, method="xml", encoding="unicode")


MODIFIER_ATTRS = {
    "invisible",
    "readonly",
    "required",
    "column_invisible",
    "attrs",
}


def xml_term_adapter(term_en: str) -> Callable[[str], str | None]:
    orig_node = parse_xml(f"<div>{term_en}</div>")

    def same_struct_iter(left, right):
        if left.tag != right.tag or len(left) != len(right):
            msg = "Non matching struct"
            raise ValueError(msg)
        yield left, right
        left_iter = left.iterchildren()
        right_iter = right.iterchildren()
        for lc, rc in zip(left_iter, right_iter, strict=False):
            yield from same_struct_iter(lc, rc)

    def adapter(term):
        new_node = parse_xml(f"<div>{term}</div>")
        try:
            for orig_n, new_n in same_struct_iter(orig_node, new_node):
                removed_attrs = [
                    k
                    for k in new_n.attrib
                    if k in MODIFIER_ATTRS and k not in orig_n.attrib
                ]
                for k in removed_attrs:
                    del new_n.attrib[k]
                keep_attrs = dict(orig_n.attrib.items())
                new_n.attrib.update(keep_attrs)
        except ValueError:
            return None

        return serialize_xml(new_node)[5:-6]

    return adapter


_HTML_PARSER = etree.HTMLParser(encoding="utf8")


def parse_html(text: str) -> etree._Element:
    try:
        parse = html.fragment_fromstring(text, parser=_HTML_PARSER)
    except (etree.ParserError, TypeError) as e:
        raise UserError(_("Error while parsing view:\n\n%s") % e) from e
    return parse


def serialize_html(node: etree._Element) -> str:
    return etree.tostring(node, method="html", encoding="unicode")


def _xml_translate(
    callback: Callable[[str], str | None], value: str | None
) -> str | None:
    if not value:
        return value

    try:
        root = parse_xml(value)
        result = translate_xml_node(root, callback, serialize_xml)
        return serialize_xml(result)
    except etree.ParseError:
        root = parse_html("<div>%s</div>" % value)
        result = translate_xml_node(root, callback, serialize_xml)
        return serialize_xml(result)[5:-6]


def xml_term_converter(value: str) -> str:
    div = f"<div>{value}</div>"
    root = etree.fromstring(div, etree.HTMLParser())
    return etree.tostring(root[0][0], encoding="unicode")[5:-6]


def _html_translate(
    callback: Callable[[str], str | None], value: str | None
) -> str | None:
    if not value:
        return value

    try:
        root = parse_html("<div>%s</div>" % value)
        result = translate_xml_node(root, callback, serialize_html)
        value = serialize_html(result)[5:-6].replace("\xa0", "&nbsp;")
    except ValueError:
        _logger.exception("Cannot translate malformed HTML, using source value instead")

    return value


def html_term_converter(value: str) -> str:
    div = f"<div>{value}</div>"
    root = etree.fromstring(div, etree.HTMLParser())
    return etree.tostring(root[0][0], encoding="unicode", method="html")[5:-6]


def get_text_content(term: str) -> str:
    content = html.fromstring(term).text_content()
    return " ".join(content.split())


def is_text(term: str) -> bool:
    return len(html.fromstring(f"<div>{term}</div>")) == 0


@dataclass(frozen=True)
class TranslationDialect:
    """Everything one markup language needs in order to be translated.

    These five used to be attributes bolted onto the two translate *functions*,
    which made the set open-ended and its members optional-by-accident:
    ``xml_translate`` carried a ``term_adapter`` and ``html_translate`` did not,
    and the only statement of that fact anywhere was a ``hasattr`` in the ORM's
    translation write path. Spelled as a field with a default, the asymmetry is
    declared rather than discovered.

    Instances are callable so that ``field.translate(callback, value)`` -- and
    ``callable(field.translate)``, which the ORM tests to tell a dialect from a
    plain ``translate=True`` -- keep working unchanged.
    """

    name: str
    translate: Callable[[Callable[[str], str | None], str | None], str | None]
    get_text_content: Callable[[str], str]
    term_converter: Callable[[str], str]
    is_text: Callable[[str], bool]
    #: Only the XML dialect can adapt a term to a changed structure.
    term_adapter: Callable[[str], Callable[[str], str | None]] | None = None

    def __call__(
        self, callback: Callable[[str], str | None], value: str | None
    ) -> str | None:
        return self.translate(callback, value)

    def __repr__(self) -> str:
        return f"<TranslationDialect {self.name}>"


xml_translate = TranslationDialect(
    name="xml_translate",
    translate=_xml_translate,
    get_text_content=get_text_content,
    term_converter=xml_term_converter,
    is_text=is_text,
    term_adapter=xml_term_adapter,
)

html_translate = TranslationDialect(
    name="html_translate",
    translate=_html_translate,
    get_text_content=get_text_content,
    term_converter=html_term_converter,
    is_text=is_text,
)

FIELD_TRANSLATE["html_translate"] = html_translate
FIELD_TRANSLATE["xml_translate"] = xml_translate


def get_translation(module: str, lang: str, source: str, args: tuple | dict) -> str:
    assert lang, "missing language for translation"
    if lang == "en_US":
        translation = source
    else:
        assert module, "missing module name for translation"
        translation = code_translations.get_python_translations(module, lang).get(
            source, source
        )
    if not args:
        return translation
    args_is_dict = isinstance(args, dict)
    vals = args.values() if args_is_dict else args
    has_markup = has_lazy = has_iterable = False
    for v in vals:
        if isinstance(v, Markup):
            has_markup = True
        elif isinstance(v, LazyGettext):
            has_lazy = True
        elif isinstance(v, Iterable) and not isinstance(v, (str, bytes)):
            has_iterable = True
            if not has_markup and any(isinstance(el, Markup) for el in v):
                has_markup = True
        if has_markup and has_lazy and has_iterable:
            break
    if has_markup:
        translation = escape(translation)
    if has_lazy:
        if args_is_dict:
            args = {
                k: v._translate(lang) if isinstance(v, LazyGettext) else v
                for k, v in args.items()
            }
        else:
            args = tuple(
                v._translate(lang) if isinstance(v, LazyGettext) else v for v in args
            )
    if has_iterable:

        def process_translation_arg(v):
            if isinstance(v, Iterable) and not isinstance(v, (str, bytes)):
                v = [
                    el._translate(lang) if isinstance(el, LazyGettext) else el
                    for el in v
                ]
                if any(isinstance(el, Markup) for el in v):
                    v = [el if isinstance(el, Markup) else escape(el) for el in v]
                    return Markup(format_list(env=None, lst=v, lang_code=lang))
                return format_list(env=None, lst=v, lang_code=lang)
            return v

        if args_is_dict:
            args = {k: process_translation_arg(v) for k, v in args.items()}
        else:
            args = tuple(process_translation_arg(v) for v in args)
    try:
        return translation % args
    except TypeError, ValueError, KeyError:
        bad = translation
        translation = (escape(source) if has_markup else source) % args
        _logger.exception("Bad translation %r for string %r", bad, source)
    return translation


def get_translated_module(
    arg: str | int | typing.Any,
) -> str:
    if isinstance(arg, str):
        if arg.startswith("odoo.addons."):
            return arg.split(".")[2]
        if "." in arg or not arg:
            return "base"
        else:
            return arg
    else:
        if isinstance(arg, int):
            frame = inspect.currentframe()
            while arg > 0 and frame is not None:
                arg -= 1
                frame = frame.f_back
        else:
            frame = arg
        if not frame:
            return "base"
        if (module_name := frame.f_globals.get("__name__")) and module_name.startswith(
            "odoo.addons."
        ):
            return module_name.split(".")[2]
        path = inspect.getfile(frame)
        from odoo.modules import get_resource_from_path

        path_info = get_resource_from_path(path)
        return path_info.module if path_info else "base"


def _probe(obj: object, name: str) -> object:
    if obj is None:
        return None
    try:
        return object.__getattribute__(obj, name)
    except AttributeError:
        return None


def _get_cr(frame: FrameType) -> BaseCursor | None:
    if "cr" in frame.f_locals:
        return frame.f_locals["cr"]
    if "cursor" in frame.f_locals:
        return frame.f_locals["cursor"]
    if (local_self := frame.f_locals.get("self")) is not None:
        if (local_env := _probe(local_self, "env")) is not None:
            return _probe(local_env, "cr")
        if (cr := _probe(local_self, "cr")) is not None:
            return cr
    http = getattr(odoo, "http", None)
    if http and (req := http.request) and (env := req.env):
        return env.cr
    return None


def _get_uid(frame: FrameType) -> int | None:
    if "uid" in frame.f_locals:
        return frame.f_locals["uid"]
    if "user" in frame.f_locals:
        try:
            return int(frame.f_locals["user"])
        except TypeError, ValueError:
            pass
    if (local_self := frame.f_locals.get("self")) is not None:
        if (local_env := _probe(local_self, "env")) is not None:
            if uid := _probe(local_env, "uid"):
                return uid
    return None


_LANG_FRAME_SEARCH_DEPTH = 10


def _lang_search_frames(frame: FrameType | None) -> list[FrameType]:
    frames = []
    for _depth in range(_LANG_FRAME_SEARCH_DEPTH):
        if frame is None:
            break
        frames.append(frame)
        frame = frame.f_back
    return frames


def _mapping_lang(candidate: object) -> str:
    if not isinstance(candidate, Mapping):
        return ""
    lang = candidate.get("lang")
    return lang if isinstance(lang, str) else ""


def _get_frame_context_lang(frame: FrameType) -> str:
    f_locals = frame.f_locals
    if lang := _mapping_lang(f_locals.get("context")):
        return lang
    if isinstance(local_kwargs := f_locals.get("kwargs"), Mapping):
        return _mapping_lang(local_kwargs.get("context"))
    return ""


def _get_lang(frame: FrameType | None, default_lang: str = "") -> str:
    frames = _lang_search_frames(frame)
    found_env = False
    for candidate in frames:
        if lang := _get_frame_context_lang(candidate):
            return lang
        local_env = _probe(candidate.f_locals.get("self"), "env")
        if local_env:
            found_env = True
            if lang := local_env.lang:
                return lang
    http = getattr(odoo, "http", None)
    if http and (req := http.request) and (env := req.env):
        found_env = True
        if lang := env.lang:
            return lang
    for candidate in frames:
        cr = _get_cr(candidate)
        uid = _get_uid(candidate)
        if cr and uid:
            from odoo import api

            found_env = True
            env = api.Environment(cr, uid, {})
            if lang := env["res.users"].context_get().get("lang"):
                return lang
            break
    if default_lang:
        _logger.debug("no translation language detected, fallback to %s", default_lang)
        return default_lang
    _logger.log(
        logging.DEBUG if found_env else logging.WARNING,
        "no translation language detected, skipping translation %s",
        frame,
        stack_info=True,
    )
    return ""


def _get_translation_source(
    stack_level: int, module: str = "", lang: str = "", default_lang: str = ""
) -> tuple[str, str]:
    if not (module and lang):
        frame = inspect.currentframe()
        for _index in range(stack_level + 1):
            frame = frame.f_back
        lang = lang or _get_lang(frame, default_lang)
    if lang and lang != "en_US":
        return get_translated_module(module or frame), lang
    else:
        return module or "base", "en_US"


def get_text_alias(source: str, /, *args: object, **kwargs: object) -> str:
    assert not (args and kwargs)
    assert isinstance(source, str)
    module, lang = _get_translation_source(1)
    return get_translation(module, lang, source, args or kwargs)


@functools.total_ordering
class LazyGettext:
    __slots__ = ("_args", "_default_lang", "_module", "_source")

    def __init__(
        self,
        source: str,
        /,
        *args: object,
        _module: str = "",
        _default_lang: str = "",
        **kwargs: object,
    ) -> None:
        assert not (args and kwargs)
        assert isinstance(source, str)
        self._source = source
        self._args = args or kwargs
        self._module = get_translated_module(_module or 2)
        self._default_lang = _default_lang

    def _translate(self, lang: str = "") -> str:
        module, lang = _get_translation_source(
            2, self._module, lang, default_lang=self._default_lang
        )
        return get_translation(module, lang, self._source, self._args)

    def __repr__(self) -> str:
        args = {
            "_module": self._module,
            "_default_lang": self._default_lang,
            "_args": self._args,
        }
        return f"_lt({self._source!r}, **{args!r})"

    def __str__(self) -> str:
        return self._translate()

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError

    def __lt__(self, other: object) -> bool:
        raise NotImplementedError

    def __add__(self, other: object) -> str:
        if isinstance(other, str):
            return self._translate() + other
        elif isinstance(other, LazyGettext):
            return self._translate() + other._translate()
        return NotImplemented

    def __radd__(self, other: object) -> str:
        if isinstance(other, str):
            return other + self._translate()
        return NotImplemented


class LazyTranslate:
    module: str
    default_lang: str

    def __init__(self, module: str, *, default_lang: str = "") -> None:
        self.module = module = get_translated_module(module or 2)
        self.default_lang = default_lang or ("en_US" if module == "base" else "")

    def __call__(self, source: str, *args, **kwargs) -> LazyGettext:
        return LazyGettext(
            source,
            *args,
            **kwargs,
            _module=self.module,
            _default_lang=self.default_lang,
        )


_ = get_text_alias
_lt = LazyGettext


def parse_xmlid(xmlid: str, default_module: str) -> tuple[str, str]:
    split_id = xmlid.split(".", maxsplit=1)
    if len(split_id) == 1:
        return default_module, split_id[0]
    return split_id[0], split_id[1]


def translation_file_reader(
    source: IO[bytes] | IO[str], fileformat: str = "po", module: str | None = None
) -> object:
    if fileformat == "csv":
        if module is not None:
            return CSVDataFileReader(source, module)
        return CSVFileReader(source)
    if fileformat == "po":
        return PoFileReader(source)
    if fileformat == "xml":
        assert module
        return XMLDataFileReader(source, module)
    _logger.info("Bad file format: %s", fileformat)
    raise ValueError(_("Bad file format: %s", fileformat))


class CSVFileReader:
    def __init__(self, source: IO[bytes] | IO[str]) -> None:
        _reader = codecs.getreader("utf-8")
        self.source = csv.DictReader(_reader(source), quotechar='"', delimiter=",")
        self.prev_code_src = ""

    def __iter__(self) -> Iterator[dict]:
        for entry in self.source:
            if entry["res_id"] and entry["res_id"].isnumeric():
                entry["res_id"] = int(entry["res_id"])
            elif not entry.get("imd_name"):
                entry["module"], entry["imd_name"] = entry["res_id"].split(".", 1)
                entry["res_id"] = None
            if entry["type"] == "model" or entry["type"] == "model_terms":
                entry["imd_model"] = entry["name"].partition(",")[0]

            if entry["type"] == "code":
                if entry["src"] == self.prev_code_src:
                    continue
                self.prev_code_src = entry["src"]

            yield entry


class CSVDataFileReader:
    def __init__(self, source: IO[bytes] | IO[str], module: str) -> None:
        _reader = codecs.getreader("utf-8")
        self.module = module
        self.model = Path(source.name).stem.split("-")[0]
        self.source = csv.DictReader(_reader(source), quotechar='"', delimiter=",")
        self.prev_code_src = ""

    def __iter__(self) -> Iterator[dict]:
        translated_fnames = sorted(
            [
                fname.split("@", maxsplit=1)
                for fname in self.source.fieldnames or []
                if "@" in fname
            ],
            key=lambda x: x[1],
        )
        for entry in self.source:
            for fname, lang in translated_fnames:
                module, imd_name = parse_xmlid(entry["id"], self.module)
                yield {
                    "type": "model",
                    "imd_model": self.model,
                    "imd_name": imd_name,
                    "lang": lang,
                    "value": entry[f"{fname}@{lang}"],
                    "src": entry[fname],
                    "module": module,
                    "name": f"{self.model},{fname}",
                }


class XMLDataFileReader:
    def __init__(self, source: IO[bytes] | IO[str], module: str) -> None:
        try:
            tree = etree.parse(source)
        except etree.LxmlSyntaxError:
            _logger.warning("Error parsing XML file %s", source)
            tree = etree.fromstring("<data/>")
        self.source = tree
        self.module = module

    def __iter__(self) -> Iterator[dict]:
        for record in self.source.xpath("//field[contains(@name, '@')]/.."):
            vals = {field.attrib["name"]: field.text for field in record.xpath("field")}
            translated_fnames = sorted(
                [fname.split("@", maxsplit=1) for fname in vals if "@" in fname],
                key=lambda x: x[1],
            )
            for fname, lang in translated_fnames:
                module, imd_name = parse_xmlid(record.attrib["id"], self.module)
                yield {
                    "type": "model",
                    "imd_model": record.attrib["model"],
                    "imd_name": imd_name,
                    "lang": lang,
                    "value": vals[f"{fname}@{lang}"],
                    "src": vals[fname],
                    "module": module,
                    "name": f"{record.attrib['model']},{fname}",
                }


class PoFileReader:
    def __init__(self, source: str | object) -> None:
        def get_pot_path(source_name):
            if isinstance(source_name, str) and source_name.endswith(".po"):
                path = Path(source_name)
                filename = path.parent.parent.name + ".pot"
                pot_path = path.with_name(filename)
                return (pot_path.exists() and str(pot_path)) or False
            return False

        if isinstance(source, str):
            self.pofile = polib.pofile(source)
            pot_path = get_pot_path(source)
        else:
            self.pofile = polib.pofile(source.read().decode())
            pot_path = get_pot_path(source.name)

        if pot_path:
            self.pofile.merge(polib.pofile(pot_path))

    def __iter__(self) -> Iterator[dict]:
        for entry in self.pofile:
            if entry.obsolete:
                continue

            comment = entry.comment or ""
            comment_match = re.match(r"(module[s]?): (\w+)", comment)
            module = comment_match.group(2) if comment_match else None
            comments = "\n".join(
                c for c in comment.split("\n") if not c.startswith("module:")
            )
            source = entry.msgid
            translation = entry.msgstr
            found_code_occurrence = False
            for occurrence, line_number in entry.occurrences:
                match = re.match(
                    r"(model|model_terms):([\w.]+),([\w]+):(\w+)\.([^ ]+)",
                    occurrence,
                )
                if match:
                    type, model_name, field_name, module, xmlid = match.groups()
                    yield {
                        "type": type,
                        "imd_model": model_name,
                        "name": model_name + "," + field_name,
                        "imd_name": xmlid,
                        "res_id": None,
                        "src": source,
                        "value": translation,
                        "comments": comments,
                        "module": module,
                    }
                    continue

                match = re.match(r"(code):([\w/.]+)", occurrence)
                if match:
                    type, name = match.groups()
                    if found_code_occurrence:
                        continue
                    found_code_occurrence = True
                    yield {
                        "type": type,
                        "name": name,
                        "src": source,
                        "value": translation,
                        "comments": comments,
                        "res_id": int(line_number),
                        "module": module,
                    }
                    continue

                match = re.match(r"(selection):([\w.]+),([\w]+)", occurrence)
                if match:
                    _logger.info("Skipped deprecated occurrence %s", occurrence)
                    continue

                match = re.match(r"(sql_constraint|constraint):([\w.]+)", occurrence)
                if match:
                    _logger.info("Skipped deprecated occurrence %s", occurrence)
                    continue
                _logger.error("malformed po file: unknown occurrence: %s", occurrence)


def TranslationFileWriter(
    target: IO[bytes] | IO[str], fileformat: str = "po", lang: str | None = None
) -> object:
    if fileformat == "csv":
        return CSVFileWriter(target)

    if fileformat == "po":
        return PoFileWriter(target, lang=lang)

    if fileformat == "tgz":
        return TarFileWriter(target, lang=lang)

    raise ValueError(
        _("Unrecognized extension: must be one of .csv, .po, or .tgz (received .%s).")
        % fileformat
    )


_writer = codecs.getwriter("utf-8")


class _UnixDialect(csv.excel):
    """Excel's quoting, LF line endings.

    Neither stdlib dialect is this: `excel` writes CRLF, `unix` quotes every
    field. It is ours, so it lives with its one caller rather than in the
    stdlib registry under a global name.
    """

    lineterminator = "\n"


class CSVFileWriter:
    def __init__(self, target: IO[bytes] | IO[str]) -> None:
        self.writer = csv.writer(_writer(target), dialect=_UnixDialect)
        self.writer.writerow(
            ("module", "type", "name", "res_id", "src", "value", "comments")
        )

    def write_rows(self, rows: Iterable) -> None:
        for module, type, name, res_id, src, trad, comments in rows:
            comments = "\n".join(comments)
            self.writer.writerow((module, type, name, res_id, src, trad, comments))


class PoFileWriter:
    def __init__(self, target: IO[bytes] | IO[str], lang: str | None) -> None:
        self.buffer = target
        self.lang = lang
        self.po = polib.POFile()

    def write_rows(self, rows: Iterable) -> None:
        grouped_rows: dict[str, dict[str, Any]] = {}
        modules = set()
        for module, type, name, res_id, src, trad, comments in rows:
            row = grouped_rows.setdefault(src, {})
            row.setdefault("modules", set()).add(module)
            if not row.get("translation") and trad != src:
                row["translation"] = trad
            row.setdefault("tnrs", []).append((type, name, res_id))
            row.setdefault("comments", set()).update(comments)
            modules.add(module)

        for src, row in sorted(grouped_rows.items()):
            if not self.lang or not row.get("translation"):
                row["translation"] = ""
            self.add_entry(
                sorted(row["modules"]),
                sorted(row["tnrs"]),
                src,
                row["translation"],
                sorted(row["comments"]),
            )

        self.po.header = (
            "Translation of %s.\n"
            "This file contains the translation of the following modules:\n"
            "%s"
            % (
                odoo.release.description,
                "".join("\t* %s\n" % m for m in modules),
            )
        )
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M+0000")
        self.po.metadata = {
            "Project-Id-Version": "%s %s"
            % (odoo.release.description, odoo.release.version),
            "Report-Msgid-Bugs-To": "",
            "POT-Creation-Date": now,
            "PO-Revision-Date": now,
            "Last-Translator": "",
            "Language-Team": "",
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=UTF-8",
            "Content-Transfer-Encoding": "",
            "Plural-Forms": "",
        }

        self.buffer.write(str(self.po).encode())

    def add_entry(
        self,
        modules: list[str],
        tnrs: list,
        source: str,
        trad: str,
        comments: list[str] | None = None,
    ) -> None:
        entry = polib.POEntry(
            msgid=source,
            msgstr=trad,
        )
        plural = (len(modules) > 1 and "s") or ""
        entry.comment = "module%s: %s" % (plural, ", ".join(modules))
        if comments:
            entry.comment += "\n" + "\n".join(comments)
        occurrences: OrderedSet[str] = OrderedSet()
        for type_, *ref in tnrs:
            if type_ == "code":
                fpath, lineno = ref
                name = f"code:{fpath}"
                lineno = "0"
            else:
                field_name, xmlid = ref
                name = f"{type_}:{field_name}:{xmlid}"
                lineno = None
            occurrences.add((name, lineno))
        entry.occurrences = list(occurrences)
        self.po.append(entry)


class TarFileWriter:
    def __init__(self, target: IO[bytes] | IO[str], lang: str | None) -> None:
        self.tar = tarfile.open(fileobj=target, mode="w|gz")  # noqa: SIM115  instance-owned, closed in write_rows
        self.lang = lang

    def write_rows(self, rows: Iterable) -> None:
        rows_by_module = defaultdict(list)
        for row in rows:
            module = row[0]
            rows_by_module[module].append(row)

        for mod, modrows in rows_by_module.items():
            with io.BytesIO() as buf:
                po = PoFileWriter(buf, lang=self.lang)
                po.write_rows(modrows)
                buf.seek(0)

                ext = "po" if self.lang else "pot"
                info = tarfile.TarInfo(
                    str(Path(mod, "i18n", f"{self.lang or mod}.{ext}"))
                )
                info.size = len(buf.getvalue())

                self.tar.addfile(info, fileobj=buf)

        self.tar.close()


def trans_export(
    lang: str, modules: list[str], buffer: IO[bytes], format: str, env: Environment
) -> bool:
    reader = TranslationModuleReader(env.cr, modules=modules, lang=lang)
    if not reader:
        return False
    writer = TranslationFileWriter(buffer, fileformat=format, lang=lang)
    writer.write_rows(reader)
    return True


def trans_export_records(
    lang: str,
    model_name: str,
    ids: list[int],
    buffer: IO[bytes],
    format: str,
    env: Environment,
) -> bool:
    reader = TranslationRecordReader(env.cr, model_name, ids, lang=lang)
    if not reader:
        return False
    writer = TranslationFileWriter(buffer, fileformat=format, lang=lang)
    writer.write_rows(reader)
    return True


def _push(
    callback: Callable[[str, int], None], term: str | None, source_line: int
) -> None:
    term = (term or "").strip()
    if any(x.isalpha() for x in term):
        callback(term, source_line)


def _extract_translatable_qweb_terms(
    element: etree._Element, callback: Callable[[str, int], None]
) -> None:
    for el in element:
        if isinstance(el, SKIPPED_ELEMENT_TYPES):
            continue
        if (
            el.tag.lower() not in SKIPPED_ELEMENTS
            and "t-js" not in el.attrib
            and not (
                el.tag == "attribute" and not is_translatable_attrib(el.get("name"), el)
            )
            and el.get("t-translation", "").strip() != "off"
        ):
            _push(callback, el.text, el.sourceline)
            is_component = (
                el.tag[0].isupper()
                or "t-component" in el.attrib
                or "t-set-slot" in el.attrib
            )
            for attr in el.attrib:
                if (not is_component and attr in OWL_TRANSLATED_ATTRS) or (
                    is_component and attr.endswith(".translate")
                ):
                    _push(callback, el.attrib[attr], el.sourceline)
            _extract_translatable_qweb_terms(el, callback)
        _push(callback, el.tail, el.sourceline)


def babel_extract_qweb(
    fileobj: IO[bytes], keywords: list, comment_tags: list, options: dict
) -> list[tuple]:
    result: list[tuple] = []

    def handle_text(text, lineno):
        result.append((lineno, None, text, []))

    tree = etree.parse(fileobj)
    _extract_translatable_qweb_terms(tree.getroot(), handle_text)
    return result


def extract_formula_terms(formula: str) -> Iterator[str]:
    tokens = generate_tokens(io.StringIO(formula).readline)
    tokens = (token for token in tokens if token.type not in {NEWLINE, INDENT, DEDENT})
    for t1 in tokens:
        if t1.string != "_t":
            continue
        t2 = next(tokens, None)
        if t2 and t2.string == "(":
            t3 = next(tokens, None)
            t4 = next(tokens, None)
            if t4 and t4.string == ")" and t3 and t3.type == STRING:
                yield t3.string[1:][:-1]


def extract_spreadsheet_terms(
    fileobj: IO[bytes], keywords: list, comment_tags: list, options: dict
) -> Iterator[tuple]:
    terms: set[tuple] = set()
    data = json.load(fileobj)
    for sheet in data.get("sheets", []):
        for cell in sheet["cells"].values():
            content = cell if isinstance(cell, str) else cell.get("content", "")
            if content.startswith("="):
                terms.update(extract_formula_terms(content))
            else:
                markdown_link = re.fullmatch(r"\[(.+)\]\(.+\)", content)
                if markdown_link:
                    terms.add(markdown_link[1])
        for figure in sheet["figures"]:
            if figure["tag"] == "chart":
                title = figure["data"]["title"]
                if isinstance(title, str):
                    terms.add(title)
                elif "text" in title:
                    terms.add(title["text"])
                if "axesDesign" in figure["data"]:
                    terms.update(
                        axes.get("title", {}).get("text", "")
                        for axes in figure["data"]["axesDesign"].values()
                    )
                if "text" in (baselineDescr := figure["data"].get("baselineDescr", {})):
                    terms.add(baselineDescr["text"])
                if "text" in (keyDescr := figure["data"].get("keyDescr", {})):
                    terms.add(keyDescr["text"])
    terms.update(
        global_filter["label"] for global_filter in data.get("globalFilters", [])
    )
    return ((0, None, term, []) for term in terms if any(x.isalpha() for x in term))


class ImdInfo(typing.NamedTuple):
    name: str
    model: str
    res_id: int
    module: str


class TranslationReader:
    def __init__(self, cr: BaseCursor, lang: str | None = None) -> None:
        self._cr = cr
        self._lang = lang or "en_US"
        from odoo import api

        self.env = api.Environment(cr, api.SUPERUSER_ID, {})
        self._to_translate: list = []

    def __bool__(self) -> bool:
        return bool(self._to_translate)

    def __iter__(self) -> Iterator[tuple]:
        for (
            module,
            source,
            name,
            res_id,
            ttype,
            comments,
            _record_id,
            value,
        ) in self._to_translate:
            yield (module, ttype, name, res_id, source, value, comments)

    def _push_translation(
        self,
        module: str,
        ttype: str,
        name: str,
        res_id: str | int | None,
        source: str,
        comments: list | None = None,
        record_id: int | None = None,
        value: str | None = None,
    ) -> None:
        sanitized_term = (source or "").strip()
        if not any(c.isalpha() for c in sanitized_term):
            return
        self._to_translate.append(
            (
                module,
                source,
                name,
                res_id,
                ttype,
                tuple(comments or ()),
                record_id,
                value,
            )
        )

    def _export_imdinfo(self, model: str, imd_per_id: dict[int, ImdInfo]):
        records = self._get_translatable_records(imd_per_id.values())
        if not records:
            return

        env = records.env
        for record in records.with_context(check_translations=True):
            module = imd_per_id[record.id].module
            xml_name = "%s.%s" % (module, imd_per_id[record.id].name)
            for field_name, field in record._fields.items():
                if (
                    not (field.translate and field.store)
                    or str(field) == "ir.actions.actions.name"
                    or (
                        str(field) == "ir.model.fields.field_description"
                        and not env[record.model]
                        ._fields[record.name]
                        .export_string_translation
                    )
                ):
                    continue
                name = model + "," + field_name
                value_en = record[field_name] or ""
                value_lang = record.with_context(lang=self._lang)[field_name] or ""
                trans_type = "model_terms" if callable(field.translate) else "model"
                try:
                    translation_dictionary = field.get_translation_dictionary(
                        value_en, {self._lang: value_lang}
                    )
                except Exception:
                    _logger.exception(
                        "Failed to extract terms from %s %s", xml_name, name
                    )
                    continue
                for term_en, term_langs in translation_dictionary.items():
                    term_lang = term_langs.get(self._lang)
                    self._push_translation(
                        module,
                        trans_type,
                        name,
                        xml_name,
                        term_en,
                        record_id=record.id,
                        value=term_lang if term_lang != term_en else "",
                    )

    def _get_translatable_records(self, imd_records: object) -> object:
        model = next(iter(imd_records)).model
        if model not in self.env:
            _logger.error("Unable to find object %r", model)
            return self.env["_unknown"].browse()

        if not self.env[model]._translate:
            return self.env[model].browse()

        res_ids = [r.res_id for r in imd_records]
        records = self.env[model].browse(res_ids).exists()
        if len(records) < len(res_ids):
            missing_ids = set(res_ids) - set(records.ids)
            missing_records = [
                f"{r.module}.{r.name}" for r in imd_records if r.res_id in missing_ids
            ]
            _logger.warning(
                "Unable to find records of type %r with external ids %s",
                model,
                ", ".join(missing_records),
            )
            if not records:
                return records

        if model == "ir.model.fields.selection":
            fields = defaultdict(lambda: self.env["ir.model.fields.selection"])
            for selection in records:
                fields[selection.field_id] |= selection
            for field, selection in fields.items():
                field_name = field.name
                field_model = self.env.get(field.model)
                if (
                    field_model is None
                    or not field_model._translate
                    or field_name not in field_model._fields
                ):
                    records -= selection
        elif model == "ir.model.fields":
            for field in records:
                field_name = field.name
                field_model = self.env.get(field.model)
                if (
                    field_model is None
                    or not field_model._translate
                    or field_name not in field_model._fields
                ):
                    records -= field  # noqa: B909  recordsets are immutable: -= rebinds, the iterator keeps the original

        return records


class TranslationRecordReader(TranslationReader):
    def __init__(
        self,
        cr: object,
        model_name: str,
        ids: list[int],
        field_names: list[str] | None = None,
        lang: str | None = None,
    ) -> None:
        super().__init__(cr, lang)
        self._records = self.env[model_name].browse(ids)
        self._field_names = field_names or list(self._records._fields.keys())

        self._export_translatable_records(self._records, self._field_names)

    def _export_translatable_records(
        self, records: object, field_names: list[str]
    ) -> None:
        if not records:
            return

        fields = records._fields

        if records._inherits:
            inherited_fields = defaultdict(list)
            for field_name in field_names:
                field = records._fields[field_name]
                if field.translate and not field.store and field.inherited_field:
                    inherited_fields[field.inherited_field.model_name].append(
                        field_name
                    )
            for parent_mname, parent_fname in records._inherits.items():
                if parent_mname in inherited_fields:
                    self._export_translatable_records(
                        records[parent_fname], inherited_fields[parent_mname]
                    )

        if not any(
            fields[field_name].translate and fields[field_name].store
            for field_name in field_names
        ):
            return

        records._ensure_xml_ids()

        model_name = records._name
        query = """SELECT min(concat(module, '.', name)), res_id
                             FROM ir_model_data
                            WHERE model = %s
                              AND res_id = ANY(%s)
                         GROUP BY model, res_id"""

        self._cr.execute(query, (model_name, records.ids))

        imd_per_id = {
            res_id: ImdInfo(
                (tmp := module_xml_name.split(".", 1))[1],
                model_name,
                res_id,
                tmp[0],
            )
            for module_xml_name, res_id in self._cr.fetchall()
        }

        self._export_imdinfo(model_name, imd_per_id)


class TranslationModuleReader(TranslationReader):
    def __init__(
        self, cr: object, modules: list[str] | None = None, lang: str | None = None
    ) -> None:
        super().__init__(cr, lang)
        self._modules = modules or ["all"]
        self._path_list = [(path, True, True) for path in odoo.addons.__path__]
        self._installed_modules = [
            m["name"]
            for m in self.env["ir.module.module"].search_read(
                [("state", "=", "installed")], fields=["name"]
            )
        ]

        self._export_translatable_records()
        self._export_translatable_resources()

    def _export_translatable_records(self) -> None:
        modules = (
            self._installed_modules if "all" in self._modules else list(self._modules)
        )
        xml_defined: set[str] = set()
        for module in modules:
            for filepath in get_datafile_translation_path(module):
                fileformat = Path(filepath).suffix[1:].lower()
                with file_open(filepath, mode="rb") as source:
                    xml_defined.update(
                        (entry["imd_model"], module, entry["imd_name"])
                        for entry in translation_file_reader(
                            source, fileformat=fileformat, module=module
                        )
                    )

        query = """SELECT min(name), model, res_id, module
                     FROM ir_model_data
                    WHERE module = ANY(%s)
                 GROUP BY model, res_id, module
                 ORDER BY module, model, min(name)"""

        self._cr.execute(query, (modules,))

        records_per_model: defaultdict[str, dict] = defaultdict(dict)
        for imd_name, model, res_id, module in self._cr.fetchall():
            if (model, module, imd_name) in xml_defined:
                continue
            records_per_model[model][res_id] = ImdInfo(imd_name, model, res_id, module)

        for model, imd_per_id in records_per_model.items():
            self._export_imdinfo(model, imd_per_id)

    def _get_module_from_path(self, path: str) -> str:
        p = Path(path)
        for mp, _recursive, is_addons_root in self._path_list:
            mp_path = Path(mp)
            try:
                rel = p.relative_to(mp_path)
            except ValueError:
                continue
            if is_addons_root and str(p.parent) != str(mp_path):
                return rel.parts[0]
        return "base"

    def _verified_module_filepaths(
        self, fname: str, path: str, root: str
    ) -> tuple[str | None, str | None, str | None, str | None]:
        fabsolutepath = str(Path(root, fname))
        frelativepath = fabsolutepath.removeprefix(path)
        display_path = f"addons{frelativepath}"
        module = self._get_module_from_path(fabsolutepath)
        if (
            "all" in self._modules or module in self._modules
        ) and module in self._installed_modules:
            display_path = display_path.replace(os.sep, "/")
            return module, fabsolutepath, frelativepath, display_path
        return None, None, None, None

    def _babel_extract_terms(
        self,
        fname: str,
        path: str,
        root: str,
        extract_method: str = "odoo.tools.babel_extractors:extract_python",
        trans_type: str = "code",
        extra_comments: list[str] | None = None,
        extract_keywords: dict | None = None,
    ) -> None:
        if extract_keywords is None:
            extract_keywords = {"_": None}
        module, fabsolutepath, _, display_path = self._verified_module_filepaths(
            fname, path, root
        )
        if not module:
            return
        extra_comments = extra_comments or []
        src_file = file_open(fabsolutepath, "rb")
        options = {}
        if "python" in extract_method:
            options["encoding"] = "UTF-8"
            translations = code_translations.get_python_translations(module, self._lang)
        else:
            translations = code_translations.get_web_translations(module, self._lang)
            translations = {
                tran["id"]: tran["string"] for tran in translations["messages"]
            }
        try:
            for extracted in extract.extract(
                extract_method,
                src_file,
                keywords=extract_keywords,
                options=options,
            ):
                lineno, message, comments = extracted[:3]
                value = translations.get(message, "")
                self._push_translation(
                    module,
                    trans_type,
                    display_path,
                    lineno,
                    message,
                    comments + extra_comments,
                    value=value,
                )
        except Exception:
            _logger.exception("Failed to extract terms from %s", fabsolutepath)
        finally:
            src_file.close()

    def _export_translatable_resources(self) -> None:

        for bin_path in ["orm", "osv", "report", "modules", "service", "tools"]:
            self._path_list.append((str(Path(config.root_path, bin_path)), True, False))
        self._path_list.append((config.root_path, False, False))
        _logger.debug("Scanning modules at paths: %s", self._path_list)

        spreadsheet_files_regex = re.compile(r".*_dashboard(\.osheet)?\.json$")

        for path, recursive, _is_addons_root in self._path_list:
            _logger.debug("Scanning files of modules at %s", path)
            for root, _dummy, files in os.walk(path, followlinks=True):
                for fname in fnmatch.filter(files, "*.py"):
                    self._babel_extract_terms(
                        fname,
                        path,
                        root,
                        "odoo.tools.babel_extractors:extract_python",
                        extra_comments=[PYTHON_TRANSLATION_COMMENT],
                        extract_keywords={"_": None, "_lt": None},
                    )
                if fnmatch.fnmatch(root, "*/static/src*"):
                    for fname in fnmatch.filter(files, "*.js"):
                        self._babel_extract_terms(
                            fname,
                            path,
                            root,
                            "odoo.tools.babel_extractors:extract_javascript",
                            extra_comments=[JAVASCRIPT_TRANSLATION_COMMENT],
                            extract_keywords={"_t": None},
                        )
                    for fname in fnmatch.filter(files, "*.xml"):
                        self._babel_extract_terms(
                            fname,
                            path,
                            root,
                            "odoo.tools.translate:babel_extract_qweb",
                            extra_comments=[JAVASCRIPT_TRANSLATION_COMMENT],
                        )
                if fnmatch.fnmatch(root, "*/data/*"):
                    for fname in filter(spreadsheet_files_regex.match, files):
                        self._babel_extract_terms(
                            fname,
                            path,
                            root,
                            "odoo.tools.translate:extract_spreadsheet_terms",
                            extra_comments=[JAVASCRIPT_TRANSLATION_COMMENT],
                        )
                if not recursive:
                    break

        IrModuleModule = self.env["ir.module.module"]
        for module in self._modules:
            for translation in IrModuleModule._extract_resource_attachment_translations(
                module, self._lang
            ):
                self._push_translation(*translation)


def DeepDefaultDict() -> defaultdict:
    return defaultdict(DeepDefaultDict)


class TranslationImporter:
    def __init__(self, cr: BaseCursor, verbose: bool = True) -> None:
        self.cr = cr
        self.verbose = verbose
        from odoo import api

        self.env = api.Environment(cr, api.SUPERUSER_ID, {})

        self.model_translations = DeepDefaultDict()
        self.model_terms_translations = DeepDefaultDict()
        self.imported_langs: set[str] = set()

    def load_file(
        self,
        filepath: str,
        lang: str,
        xmlids: set[str] | None = None,
        module: str | None = None,
    ) -> None:
        with (
            suppress(FileNotFoundError),
            file_open(filepath, mode="rb", env=self.env) as fileobj,
        ):
            if self.verbose:
                _logger.info(
                    "loading base translation file %s for language %s",
                    filepath,
                    lang,
                )
            fileformat = Path(filepath).suffix[1:].lower()
            self.load(fileobj, fileformat, lang, xmlids=xmlids, module=module)

    def load(
        self,
        fileobj: object,
        fileformat: str,
        lang: str,
        xmlids: set[str] | None = None,
        module: str | None = None,
    ) -> None:
        if self.verbose:
            _logger.info("loading translation file for language %s", lang)
        if not self.env["res.lang"]._lang_get(lang):
            _logger.error(
                "Couldn't read translation for lang '%s', language not found",
                lang,
            )
            return
        try:
            fileobj.seek(0)
            reader = translation_file_reader(
                fileobj, fileformat=fileformat, module=module
            )
            self._load(reader, lang, xmlids)
        except OSError:
            iso_lang = get_iso_codes(lang)
            filename = "[lang: %s][format: %s]" % (
                iso_lang or "new",
                fileformat,
            )
            _logger.exception("couldn't read translation file %s", filename)

    def _load(self, reader: object, lang: str, xmlids: set[str] | None = None) -> None:
        if xmlids and not isinstance(xmlids, set):
            xmlids = set(xmlids)
        valid_langs = get_base_langs(lang)
        rows = sorted(
            reader,
            key=lambda r: (
                valid_langs.index(r.get("lang", lang))
                if r.get("lang", lang) in valid_langs
                else -1
            ),
        )
        for row in rows:
            if not row.get("value") or not row.get("src"):
                continue
            if row.get("type") == "code":
                continue
            if row.get("lang", lang) not in valid_langs:
                continue
            model_name = row.get("imd_model")
            module_name = row["module"]
            if model_name not in self.env:
                continue
            field_name = row["name"].split(",")[1]
            field = self.env[model_name]._fields.get(field_name)
            if not field or not field.translate or not field.store:
                continue
            xmlid = module_name + "." + row["imd_name"]
            if xmlids and xmlid not in xmlids:
                continue
            if row.get("type") == "model" and field.translate is True:
                self.model_translations[model_name][field_name][xmlid][lang] = row[
                    "value"
                ]
                self.imported_langs.add(lang)
            elif row.get("type") == "model_terms" and callable(field.translate):
                self.model_terms_translations[model_name][field_name][xmlid][
                    row["src"]
                ][lang] = row["value"]
                self.imported_langs.add(lang)

    def save(self, overwrite: bool = False, force_overwrite: bool = False) -> None:
        if not self.model_translations and not self.model_terms_translations:
            return

        cr = self.cr
        env = self.env
        env.flush_all()

        for (
            model_name,
            model_dictionary,
        ) in self.model_terms_translations.items():
            Model = env[model_name]
            model_table = Model._table
            fields = Model._fields
            for field_name, field_dictionary in model_dictionary.items():
                field = fields.get(field_name)
                for sub_xmlids in batched(
                    field_dictionary.keys(), cr.BATCH_SIZE, strict=False
                ):
                    params = []
                    for xmlid in sub_xmlids:
                        params.extend(xmlid.split(".", maxsplit=1))
                    cr.execute(
                        f"""
                        SELECT m.id, imd.module || '.' || imd.name, m."{field_name}", imd.noupdate
                        FROM "{model_table}" m, "ir_model_data" imd
                        WHERE m.id = imd.res_id
                        AND ({" OR ".join(["(imd.module = %s AND imd.name = %s)"] * (len(params) // 2))})
                    """,
                        params,
                    )

                    rows_by_id: dict[int, tuple] = {}
                    for id_, xmlid, values, noupdate in cr.fetchall():
                        if not values:
                            continue
                        entry = rows_by_id.get(id_)
                        if entry is None:
                            entry = rows_by_id[id_] = [values, noupdate, {}]
                        merged = entry[2]
                        for src, translations in field_dictionary[xmlid].items():
                            merged.setdefault(src, {}).update(translations)

                    params = []
                    for id_, (
                        values,
                        noupdate,
                        record_dictionary,
                    ) in rows_by_id.items():
                        _value_en = values.get("_en_US", values["en_US"])
                        if not _value_en:
                            continue

                        langs = {
                            lang
                            for translations in record_dictionary.values()
                            for lang in translations
                        }
                        translation_dictionary = field.get_translation_dictionary(
                            _value_en,
                            {
                                k: values.get(f"_{k}", v)
                                for k, v in values.items()
                                if k in langs
                            },
                        )

                        if force_overwrite or (not noupdate and overwrite):
                            for (
                                term_en,
                                translations,
                            ) in record_dictionary.items():
                                translation_dictionary[term_en].update(translations)
                        else:
                            for (
                                term_en,
                                translations,
                            ) in record_dictionary.items():
                                translations.update(
                                    {
                                        k: v
                                        for k, v in translation_dictionary[
                                            term_en
                                        ].items()
                                        if v != term_en
                                    }
                                )
                                translation_dictionary[term_en] = translations

                        changed_values = {}
                        for lang in langs:
                            new_val = field.translate(
                                lambda term, td=translation_dictionary, lang=lang: (
                                    td.get(term, {}).get(lang)
                                ),
                                _value_en,
                            )
                            if values.get(lang, None) != new_val:
                                changed_values[lang] = new_val
                            if f"_{lang}" in values:
                                changed_values[f"_{lang}"] = None
                        if changed_values:
                            params.extend((id_, Json(changed_values)))
                    if params:
                        env.cr.execute(
                            f"""
                            UPDATE "{model_table}" AS m
                            SET "{field_name}" = jsonb_strip_nulls("{field_name}" || t.value)
                            FROM (
                                VALUES {", ".join(["(%s, %s::jsonb)"] * (len(params) // 2))}
                            ) AS t(id, value)
                            WHERE m.id = t.id
                        """,
                            params,
                        )

        self.model_terms_translations.clear()

        for model_name, model_dictionary in self.model_translations.items():
            Model = env[model_name]
            model_table = Model._table
            for field_name, field_dictionary in model_dictionary.items():
                for sub_field_dictionary in batched(
                    field_dictionary.items(), cr.BATCH_SIZE, strict=False
                ):
                    params = []
                    for xmlid, translations in sub_field_dictionary:
                        params.extend(
                            [*xmlid.split(".", maxsplit=1), Json(translations)]
                        )
                    if not force_overwrite:
                        value_query = f"""CASE WHEN {overwrite} IS TRUE AND imd.noupdate IS NOT TRUE
                        THEN m."{field_name}" || t.value
                        ELSE t.value || m."{field_name}"END"""
                    else:
                        value_query = f'm."{field_name}" || t.value'
                    env.cr.execute(
                        f"""
                        UPDATE "{model_table}" AS m
                        SET "{field_name}" = {value_query}
                        FROM (
                            VALUES {", ".join(["(%s, %s, %s::jsonb)"] * (len(params) // 3))}
                        ) AS t(imd_module, imd_name, value)
                        JOIN "ir_model_data" AS imd
                        ON imd."model" = '{model_name}' AND imd.name = t.imd_name AND imd.module = t.imd_module
                        WHERE imd."res_id" = m."id"
                    """,
                        params,
                    )

        self.model_translations.clear()

        env.invalidate_all()
        env.registry.clear_cache()
        if self.verbose:
            _logger.info("translations are loaded successfully")


def get_locales(lang: str | None = None) -> Iterator[str]:
    if lang is None:
        lang = locale.getlocale()[0]

    def process(enc):
        ln = locale._build_localename((lang, enc))
        yield ln
        nln = locale.normalize(ln)
        if nln != ln:
            yield nln

    for x in process("utf8"):
        yield x

    prefenc = locale.getpreferredencoding()
    if prefenc:
        for x in process(prefenc):
            yield x

        prefenc = {
            "latin1": "latin9",
            "iso-8859-1": "iso8859-15",
            "cp1252": "1252",
        }.get(prefenc.lower())
        if prefenc:
            for x in process(prefenc):
                yield x

    yield lang


def resetlocale() -> str | None:
    for ln in get_locales():
        try:
            return locale.setlocale(locale.LC_ALL, ln)
        except locale.Error:
            continue
    return None


def load_language(cr: BaseCursor, lang: str) -> None:
    from odoo import api

    env = api.Environment(cr, api.SUPERUSER_ID, {})
    lang_ids = (
        env["res.lang"]
        .with_context(active_test=False)
        .search([("code", "=", lang)])
        .ids
    )
    installer = env["base.language.install"].create({"lang_ids": [(6, 0, lang_ids)]})
    installer.lang_install()


def get_base_langs(lang: str) -> list[str]:
    base_lang = lang.split("_", 1)[0]
    langs = [base_lang]
    if base_lang == "es" and lang not in ("es_ES", "es_419"):
        langs.append("es_419")
    if lang == "zh_HK":
        langs.append("zh_TW")
    if lang != base_lang:
        langs.append(lang)
    return langs


def get_po_paths(module_name: str, lang: str) -> Iterator[str]:
    po_paths = (
        str(Path(module_name, dir_, filename + ".po"))
        for filename in get_base_langs(lang)
        for dir_ in ("i18n", "i18n_extra")
    )
    for path in po_paths:
        with suppress(FileNotFoundError):
            yield file_path(path)


def get_datafile_translation_path(module_name: str) -> Iterator[str]:
    from odoo.modules import Manifest

    manifest = Manifest.for_addon(module_name, display_warning=False) or {}
    for data_type in ("data", "demo"):
        for path in manifest.get(data_type, ()):
            if path.endswith((".xml", ".csv")):
                yield file_path(str(Path(module_name, path)))


class CodeTranslations:
    def __init__(self) -> None:
        self.python_translations: dict[tuple[str, str], dict] = {}
        self.web_translations: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _read_code_translations_file(
        fileobj: object, filter_func: object
    ) -> dict[str, str]:
        translations = {}
        fileobj.seek(0)
        reader = translation_file_reader(fileobj, fileformat="po")
        for row in reader:
            if row.get("type") == "code" and row.get("src") and filter_func(row):
                translations[row["src"]] = row["value"]
        return translations

    @staticmethod
    def _get_code_translations(
        module_name: str, lang: str, filter_func: object
    ) -> dict[str, str]:
        po_paths = get_po_paths(module_name, lang)
        translations = {}
        for po_path in po_paths:
            try:
                with file_open(po_path, mode="rb") as fileobj:
                    p = CodeTranslations._read_code_translations_file(
                        fileobj, filter_func
                    )
                translations.update(p)
            except OSError:
                iso_lang = get_iso_codes(lang)
                filename = "[lang: %s][format: %s]" % (iso_lang or "new", "po")
                _logger.exception("couldn't read translation file %s", filename)
        return translations

    def _load_python_translations(self, module_name: str, lang: str) -> None:
        def filter_func(row):
            return row.get("value") and PYTHON_TRANSLATION_COMMENT in row["comments"]

        translations = CodeTranslations._get_code_translations(
            module_name, lang, filter_func
        )
        self.python_translations[(module_name, lang)] = ReadonlyDict(translations)

    def _load_web_translations(self, module_name: str, lang: str) -> None:
        def filter_func(row):
            return (
                row.get("value") and JAVASCRIPT_TRANSLATION_COMMENT in row["comments"]
            )

        translations = CodeTranslations._get_code_translations(
            module_name, lang, filter_func
        )
        self.web_translations[(module_name, lang)] = ReadonlyDict(
            {
                "messages": tuple(
                    ReadonlyDict({"id": src, "string": value})
                    for src, value in translations.items()
                )
            }
        )

    def clear(self, module_name: str | None = None) -> None:
        if module_name is None:
            self.python_translations.clear()
            self.web_translations.clear()
            return
        for cache in (self.python_translations, self.web_translations):
            for key in [k for k in cache if k[0] == module_name]:
                del cache[key]

    def get_python_translations(self, module_name: str, lang: str) -> dict[str, str]:
        if (module_name, lang) not in self.python_translations:
            self._load_python_translations(module_name, lang)
        return self.python_translations[(module_name, lang)]

    def get_web_translations(self, module_name: str, lang: str) -> dict:
        if (module_name, lang) not in self.web_translations:
            self._load_web_translations(module_name, lang)
        return self.web_translations[(module_name, lang)]


code_translations = CodeTranslations()
