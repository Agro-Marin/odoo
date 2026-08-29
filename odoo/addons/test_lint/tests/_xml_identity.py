from io import BytesIO

from lxml import etree

PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_PRESERVE_TAGS: frozenset[str] = frozenset({"pre", "textarea"})


def preserves_space(element) -> bool:
    return element.tag in _PRESERVE_TAGS or element.get(_XML_SPACE) == "preserve"


def comparable(source: bytes) -> list:
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
    try:
        return comparable(source) == comparable(rewritten)
    except etree.LxmlError:
        return False


def content(source: bytes) -> tuple[list, list]:
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
    try:
        return content(source) == content(rewritten)
    except etree.LxmlError:
        return False
