from typing import IO, Any

from lxml import etree, objectify

__all__ = ["default_parser", "fromstring", "parse", "strict_parser"]

strict_parser = etree.XMLParser(resolve_entities=False)

etree.set_default_parser(strict_parser)

default_parser = etree.XMLParser(resolve_entities=False, remove_blank_text=True)
default_parser.set_element_class_lookup(objectify.ObjectifyElementClassLookup())
objectify.set_default_parser(default_parser)


def fromstring(text: str | bytes, base_url: str | None = None) -> etree._Element:
    return etree.fromstring(text, parser=strict_parser, base_url=base_url)


def parse(source: str | IO[bytes] | Any, base_url: str | None = None) -> Any:
    return etree.parse(source, parser=strict_parser, base_url=base_url)
