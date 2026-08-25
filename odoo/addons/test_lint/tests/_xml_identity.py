"""What it means for a fixer's output to say the same thing as its input.

TWO invariants, because the two fixers are allowed different freedoms, and the
difference is the whole point:

`is_faithful` -- ORDER-PRESERVING. What `_pretty_xml` may not change: it only
reindents, so element order, comments, namespaces, text, tails and the prologue
must all survive.

`preserves_content` -- ORDER-INSENSITIVE. What `_sort_xml_records` may not
change: reordering `<field>` elements is its entire job, so its invariant is that
the same elements with the same attributes and the same words come out.

These used to be `_pretty_xml._comparable` and `test_fixers._shape`/`_words`, and
the confusing part was that the second pair was applied to the FORMATTER's output
rather than the sorter's, where it was strictly weaker than the check
`format_xml_file` had already run -- with one exception: `_comparable` squeezed
attribute values, so a rewrite collapsing `name="a   b"` to `name="a b"` passed
it and only `_shape` caught that. Because `_comparable` ran first and
short-circuited, that half was unreachable in practice.

So: the attribute-whitespace tightening moves into `is_faithful`, where it now
runs (measured over all core data files, it declines nothing that was not already
declined), and the order-insensitive pair is pointed at the fixer that actually
needs it. `_sort_xml_records` had no check at all and wrote whatever lxml
serialised, though it is the fixer that MOVES things.
"""

from io import BytesIO

from lxml import etree

PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_PRESERVE_TAGS: frozenset[str] = frozenset({"pre", "textarea"})


def preserves_space(element) -> bool:
    return element.tag in _PRESERVE_TAGS or element.get(_XML_SPACE) == "preserve"


def comparable(source: bytes) -> list:
    """Everything about `source` that a reformatting may not change."""

    def squeeze(value: str | None) -> str:
        return " ".join((value or "").split())

    out: list = []

    def walk(element, depth: int, preserve: bool = False) -> None:
        keep = preserve or (not callable(element.tag) and preserves_space(element))
        text = (element.text or "") if keep else squeeze(element.text)
        if callable(element.tag):
            out.append((depth, "#text-node", text))
        else:
            out.append(
                (
                    depth,
                    element.tag,
                    # Raw, not squeezed. An attribute value's internal whitespace
                    # is content: XML normalises individual whitespace characters
                    # to a space on parse, but never collapses a run of them, so
                    # a formatter that collapses one has changed the document.
                    tuple(sorted(element.attrib.items())),
                    tuple(sorted(element.nsmap.items(), key=lambda kv: kv[0] or "")),
                    text,
                )
            )
        for child in element:
            walk(child, depth + 1, keep)
        tail = (element.tail or "") if preserve else squeeze(element.tail)
        out.append((depth, "#tail", tail))

    tree = etree.parse(BytesIO(source), PARSER)
    root = tree.getroot()
    prologue: list = [
        source.lstrip().startswith(b"<?xml"),
        tree.docinfo.doctype,
    ]
    node = root.getprevious()
    while node is not None:
        prologue.append(("#comment" if callable(node.tag) else node.tag, node.text))
        node = node.getprevious()
    out.append(("#prologue", tuple(prologue)))

    walk(root, 0)
    return out


def is_faithful(source: bytes, rewritten: bytes) -> bool:
    """For a fixer that may not move anything -- the formatter."""
    try:
        return comparable(source) == comparable(rewritten)
    except etree.LxmlError:
        return False


def content(source: bytes) -> tuple[list, list]:
    """Every element and every word, with document order discarded.

    The invariant for a fixer whose job is to reorder: the same elements carrying
    the same attributes, and the same text, wherever they ended up.
    """
    root = etree.fromstring(source, PARSER)
    shape: list = []

    def walk(element, depth: int) -> None:
        if not callable(element.tag):
            shape.append((depth, element.tag, tuple(sorted(element.attrib.items()))))
        for child in element:
            walk(child, depth + 1)

    walk(root, 0)
    words = sorted(
        word
        for element in root.iter()
        for chunk in ((element.text or ""), (element.tail or ""))
        for word in chunk.split()
    )
    return sorted(shape), words


def preserves_content(source: bytes, rewritten: bytes) -> bool:
    """For a fixer that may move things -- the record sorter."""
    try:
        return content(source) == content(rewritten)
    except etree.LxmlError:
        return False
