from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lxml import etree

FileData = dict[str, Any]
Predicate = Callable[[FileData], bool]

CUSTOMIZATION_ID = "{*}CustomizationID"
PROFILE_ID = "{*}ProfileID"
UBL_VERSION_ID = "{*}UBLVersionID"


def is_pdf(file_data: FileData) -> bool:
    return "pdf" in file_data["mimetype"] or file_data["name"].endswith(".pdf")


def tree_satisfies(test: Callable[[Any], Any]) -> Predicate:
    """True when there is a tree and ``test(tree)`` is truthy."""

    def matches(file_data: FileData) -> bool:
        tree = file_data["xml_tree"]
        return tree is not None and bool(test(tree))

    return matches


def tree_tag_is(*tags: str) -> Predicate:
    return tree_satisfies(lambda tree: tree.tag in tags)


def tree_localname_is(name: str) -> Predicate:
    return tree_satisfies(lambda tree: etree.QName(tree).localname == name)


def findtext_equals(path: str, *values: str) -> Predicate:
    return tree_satisfies(lambda tree: tree.findtext(path) in values)


def findtext_contains(path: str, *needles: str) -> Predicate:
    def test(tree: Any) -> bool:
        text = tree.findtext(path)
        return bool(text) and any(needle in text for needle in needles)

    return tree_satisfies(test)


def findtext_startswith(path: str, prefix: str) -> Predicate:
    return tree_satisfies(lambda tree: (tree.findtext(path) or "").startswith(prefix))


def raw_contains(*needles: bytes) -> Predicate:
    def matches(file_data: FileData) -> bool:
        raw = file_data["raw"] or b""
        return all(needle in raw for needle in needles)

    return matches
