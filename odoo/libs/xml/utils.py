import re
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from collections.abc import Iterable

_CONTROL_CHAR_RE = re.compile(
    rb"[\x00-\x08\x0b\x0c\x0e-\x1f]"
    rb"|\xef\xbf[\xbe\xbf]"
    rb"|\xed[\xa0-\xbf][\x80-\xbf]"
    rb"|[\xf5-\xff]"
)


def remove_control_characters(byte_node: bytes) -> bytes:
    return _CONTROL_CHAR_RE.sub(b"", byte_node)


def create_xml_node_chain(
    first_parent_node: etree._Element,
    nodes_list: Iterable[str],
    last_node_value: str | None = None,
) -> list[etree._Element]:
    res = []
    current_node = first_parent_node
    for tag in nodes_list:
        current_node = etree.SubElement(current_node, tag)
        res.append(current_node)

    if last_node_value is not None:
        current_node.text = last_node_value
    return res


def create_xml_node(
    parent_node: etree._Element,
    node_name: str,
    node_value: str | None = None,
) -> etree._Element:
    return create_xml_node_chain(parent_node, [node_name], node_value)[0]
