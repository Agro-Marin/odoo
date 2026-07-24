"""XML helpers: control-character stripping and node construction."""

import re
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from collections.abc import Iterable

# Complement of the XML 1.0 ``Char`` production, expressed directly over UTF-8
# *bytes* (the input is bytes, and re-encoding it just to run a str pattern
# would cost a decode/encode round trip per document).
#
# This used to be written as a unicode character class that was then
# ``.encode()``d -- which does not survive the translation: the multi-byte
# sequences of ``\u0020-\ud7ff`` etc. were re-read as individual byte ranges,
# collapsing the whole class to roughly "\t\n\r plus \x20-\xf4". The result
# happened to strip C0 controls (the common case) but let U+FFFE and U+FFFF
# through -- and those are exactly what ``etree.fromstring`` rejects with
# "PCDATA invalid Char value 65534", i.e. the error this function exists to
# prevent. It also never stripped #x7F, contrary to the old docstring; #x7F is
# a legal XML Char, so the code was right and the docstring wrong.
_CONTROL_CHAR_RE = re.compile(
    rb"[\x00-\x08\x0b\x0c\x0e-\x1f]"  # C0 controls except TAB, LF, CR
    rb"|\xef\xbf[\xbe\xbf]"  # U+FFFE, U+FFFF
    rb"|\xed[\xa0-\xbf][\x80-\xbf]"  # surrogates U+D800-U+DFFF (WTF-8 input)
    rb"|[\xf5-\xff]"  # bytes that cannot start a valid UTF-8 sequence
)


def remove_control_characters(byte_node: bytes) -> bytes:
    r"""Remove the characters XML forbids from a UTF-8 byte string.

    Everything outside the XML ``Char`` production is dropped::

        Char ::= #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]

    i.e. the C0 controls other than tab/LF/CR, U+FFFE and U+FFFF, and any
    encoded surrogate.  Bytes that cannot begin a valid UTF-8 sequence are
    dropped too, since they would fail the parser just the same.  Note #x7F
    (DEL) *is* a valid XML character and is deliberately kept.

    See: https://www.w3.org/TR/xml/

    :param byte_node: XML content as UTF-8 bytes
    :return: the same content with the forbidden characters removed

    Example::

        >>> remove_control_characters("a\x03b\uffffc".encode())
        b'abc'
    """
    return _CONTROL_CHAR_RE.sub(b"", byte_node)


def create_xml_node_chain(
    first_parent_node: etree._Element,
    nodes_list: Iterable[str],
    last_node_value: str | None = None,
) -> list[etree._Element]:
    """Generate a hierarchical chain of nodes.

    Each new node being the child of the previous one based on the tags contained
    in `nodes_list`, under the given node `first_parent_node`.

    :param first_parent_node: parent of the created tree/chain
    :param nodes_list: tag names to be created
    :param last_node_value: if specified, set the last node's text to this value
    :returns: the list of created nodes

    Example::

        >>> from lxml import etree
        >>> root = etree.Element('root')
        >>> nodes = create_xml_node_chain(root, ['a', 'b', 'c'], 'value')
        >>> etree.tostring(root, encoding='unicode')
        '<root><a><b><c>value</c></b></a></root>'
    """
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
    """Create a new XML node.

    :param parent_node: parent of the created node
    :param node_name: name of the created node
    :param node_value: value of the created node (optional)
    :returns: the created node

    Example::

        >>> from lxml import etree
        >>> root = etree.Element('root')
        >>> child = create_xml_node(root, 'child', 'text')
        >>> etree.tostring(root, encoding='unicode')
        '<root><child>text</child></root>'
    """
    return create_xml_node_chain(parent_node, [node_name], node_value)[0]
