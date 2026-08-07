import copy
import functools
import itertools
import logging
import re
from typing import TYPE_CHECKING, Any

from lxml import etree
from lxml.builder import E

from odoo.libs.text.html import html_escape

if TYPE_CHECKING:
    from collections.abc import Callable


class XPathExpressionError(ValueError):
    pass


__all__ = [
    "PYTHON_ATTRIBUTES",
    "SKIPPED_ELEMENT_TYPES",
    "XPathExpressionError",
    "add_stripped_items_before",
    "add_text_before",
    "apply_inheritance_specs",
    "locate_node",
    "remove_element",
]

_logger = logging.getLogger(__name__)
RSTRIP_REGEXP = re.compile(r"\n[ \t]*$")


@functools.lru_cache(maxsize=1024)
def _compile_xpath(expr: str) -> etree.ETXPath:
    return etree.ETXPath(expr)


SKIPPED_ELEMENT_TYPES = (
    etree._Comment,
    etree._ProcessingInstruction,
    etree.CommentBase,
    etree.PIBase,
    etree._Entity,
)

PYTHON_ATTRIBUTES = {
    "readonly",
    "required",
    "invisible",
    "column_invisible",
    "t-if",
    "t-elif",
}


def add_stripped_items_before(
    node: etree._Element,
    spec: etree._Element,
    extract: Callable[[etree._Element], etree._Element],
) -> None:
    text = spec.text or ""

    before_text = ""
    prev = next(
        (
            n
            for n in node.itersiblings(preceding=True)
            if not (
                n.tag == etree.ProcessingInstruction
                and n.target == "apply-inheritance-specs-node-removal"
            )
        ),
        None,
    )
    if prev is None:
        parent = node.getparent()
        result = parent.text and RSTRIP_REGEXP.search(parent.text)
        before_text = result.group(0) if result else ""
        fallback_text = None if spec.text is None else ""
        parent.text = ((parent.text or "").rstrip() + text) or fallback_text
    else:
        result = prev.tail and RSTRIP_REGEXP.search(prev.tail)
        before_text = result.group(0) if result else ""
        prev.tail = (prev.tail or "").rstrip() + text

    if len(spec) > 0:
        spec[-1].tail = (spec[-1].tail or "").rstrip() + before_text
    else:
        spec.text = (spec.text or "").rstrip() + before_text

    for child in spec:
        if child.get("position") == "move":
            tail = child.tail
            child = extract(child)
            child.tail = tail
        node.addprevious(child)


def add_text_before(node: etree._Element, text: str | None) -> None:
    if text is None:
        return
    prev = node.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + text
    else:
        parent = node.getparent()
        parent.text = (parent.text or "").rstrip() + text


def remove_element(node: etree._Element) -> None:
    add_text_before(node, node.tail)
    node.tail = None
    node.getparent().remove(node)


def locate_node(arch: etree._Element, spec: etree._Element) -> etree._Element | None:
    if spec.tag == "xpath":
        expr = spec.get("expr")
        if not expr:
            raise ValueError("Invalid xpath specification: missing 'expr' attribute")
        try:
            xPath = _compile_xpath(expr)
        except etree.XPathSyntaxError as e:
            raise XPathExpressionError(
                f'Invalid Expression while parsing xpath "{expr}"'
            ) from e
        nodes = xPath(arch)
        return nodes[0] if nodes else None
    elif spec.tag == "field":
        for node in arch.iter("field"):
            if node.get("name") == spec.get("name"):
                return node
        return None

    for node in arch.iter(spec.tag):
        if all(
            node.get(attr) == spec.get(attr)
            for attr in spec.attrib
            if attr != "position"
        ):
            return node
    return None


def apply_inheritance_specs(
    source: etree._Element,
    specs_tree: etree._Element | list[etree._Element],
    inherit_branding: bool = False,
    pre_locate: Callable[[etree._Element], Any] | None = None,
) -> etree._Element:
    specs = list(specs_tree) if isinstance(specs_tree, list) else [specs_tree]
    pre_locate = pre_locate or (lambda _: True)

    def extract(spec: etree._Element) -> etree._Element:
        if len(spec):
            raise ValueError(
                f'Invalid specification for moved nodes: "{etree.tostring(spec, encoding="unicode")}"'
            )
        pre_locate(spec)
        to_extract = locate_node(source, spec)
        if to_extract is not None:
            remove_element(to_extract)
            return to_extract
        else:
            raise ValueError(
                f'Element "{etree.tostring(spec, encoding="unicode")}" cannot be located in parent view'
            )

    while len(specs):
        spec = specs.pop(0)
        if isinstance(spec, SKIPPED_ELEMENT_TYPES):
            continue
        if spec.tag == "data":
            specs += list(spec)
            continue
        pre_locate(spec)
        node = locate_node(source, spec)
        if node is not None:
            pos = spec.get("position", "inside")
            if pos == "replace":
                mode = spec.get("mode", "outer")
                if mode == "outer":
                    for loc in spec.xpath(".//*[text()='$0']"):
                        loc.text = ""
                        copied_node = copy.deepcopy(node)
                        if inherit_branding:
                            copied_node.set("data-oe-no-branding", "1")
                        loc.append(copied_node)
                    if node.getparent() is None:
                        spec_content = None
                        comment = None
                        for content in spec:
                            if content.tag is not etree.Comment:
                                spec_content = content
                                break
                            comment = content
                        source = copy.deepcopy(spec_content)
                        t_name = node.get("t-name")
                        if t_name:
                            source.set("t-name", t_name)
                        if comment is not None:
                            text = source.text
                            source.text = None
                            comment.tail = text
                            source.insert(0, comment)
                    else:
                        if inherit_branding and not node.get("data-oe-xpath"):
                            node.addprevious(
                                etree.ProcessingInstruction(
                                    "apply-inheritance-specs-node-removal",
                                    node.tag,
                                )
                            )

                        for child in spec:
                            if child.get("position") == "move":
                                child = extract(child)
                            node.addprevious(child)
                        node.getparent().remove(node)
                elif mode == "inner":
                    sentinel = E.sentinel()
                    if len(node) > 0:
                        node[0].addprevious(sentinel)
                    else:
                        node.append(sentinel)
                    node.text = None
                    add_stripped_items_before(sentinel, copy.deepcopy(spec), extract)
                    for child in reversed(node):
                        node.remove(child)
                        if child == sentinel:
                            break
                else:
                    raise ValueError(f'Invalid mode attribute: "{mode}"')
            elif pos == "attributes":
                for child in spec.iter("attribute"):
                    unknown = [
                        key
                        for key in child.attrib
                        if key not in ("name", "add", "remove", "separator")
                        and not key.startswith("data-oe-")
                    ]
                    if unknown:
                        raise ValueError(
                            f"Invalid attributes {', '.join(map(repr, unknown))} in element <attribute>"
                        )

                    attribute = child.get("name")
                    value = None

                    if child.get("add") or child.get("remove"):
                        if child.text:
                            raise ValueError(
                                f"Element <attribute> with 'add' or 'remove' cannot contain text {child.text!r}"
                            )
                        value = node.get(attribute, "")
                        add = child.get("add", "")
                        remove = child.get("remove", "")
                        separator = child.get("separator")

                        if attribute in PYTHON_ATTRIBUTES or attribute.startswith(
                            "decoration-"
                        ):
                            separator = (separator or "").strip()
                            if separator not in ("and", "or"):
                                raise ValueError(
                                    f"Invalid separator {separator!r} for python expression {attribute!r}; "
                                    "valid values are 'and' and 'or'"
                                )
                            if remove:
                                if re.fullmatch(rf"\(*{re.escape(remove)}\)*", value):
                                    value = ""
                                else:
                                    patterns = [
                                        f"({remove}) {separator} ",
                                        f" {separator} ({remove})",
                                        f"{remove} {separator} ",
                                        f" {separator} {remove}",
                                    ]
                                    for pattern in patterns:
                                        index = value.find(pattern)
                                        if index != -1:
                                            value = (
                                                value[:index]
                                                + value[index + len(pattern) :]
                                            )
                                            break
                            if add:
                                value = (
                                    f"({value}) {separator} ({add})" if value else add
                                )
                        else:
                            if separator is None:
                                separator = ","
                            elif separator == " ":
                                separator = None
                            values = (s.strip() for s in value.split(separator))
                            to_add = filter(
                                None, (s.strip() for s in add.split(separator))
                            )
                            to_remove = {s.strip() for s in remove.split(separator)}
                            value = (separator or " ").join(
                                itertools.chain(
                                    (v for v in values if v and v not in to_remove),
                                    to_add,
                                )
                            )
                    else:
                        value = child.text or ""

                    if value:
                        node.set(attribute, value)
                    elif attribute in node.attrib:
                        del node.attrib[attribute]
            elif pos == "inside":
                sentinel = E.sentinel()
                node.append(sentinel)
                add_stripped_items_before(sentinel, spec, extract)
                remove_element(sentinel)
            elif pos == "after":
                sentinel = E.sentinel()
                node.addnext(sentinel)
                if node.tail is not None:
                    sentinel.tail = node.tail
                    node.tail = None
                add_stripped_items_before(sentinel, spec, extract)
                remove_element(sentinel)
            elif pos == "before":
                add_stripped_items_before(node, spec, extract)

            else:
                raise ValueError(f"Invalid position attribute: '{pos}'")

        else:
            attrs = "".join(
                [
                    ' %s="%s"' % (attr, html_escape(spec.get(attr)))
                    for attr in spec.attrib
                    if attr != "position"
                ]
            )
            tag = "<%s%s>" % (spec.tag, attrs)
            raise ValueError(f"Element '{tag}' cannot be located in parent view")

    return source
