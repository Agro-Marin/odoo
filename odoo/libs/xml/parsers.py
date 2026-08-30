from typing import IO, Any

from lxml import etree, objectify

__all__ = ["default_parser", "fromstring", "parse", "strict_parser"]

# `resolve_entities=False` is stricter than lxml's own default, which is
# `'internal'`: stock lxml refuses an EXTERNAL entity but still expands an
# internal one, so a document declaring `<!ENTITY e "...">` gets it substituted.
# That is the only setting here that changes anything -- `no_network=True` and
# `decompress=False` are both already lxml's defaults, and the latter does not
# stop a gzipped *file* being decompressed by `etree.parse` in any case
# (measured on lxml 6.1.2 / libxml2 2.14.6). Passing a library default as
# though it were a hardening measure is how the shape below came to read as
# more protection than it gives.
strict_parser = etree.XMLParser(resolve_entities=False)

# `etree.set_default_parser` is THREAD-LOCAL. This call hardens the importing
# thread and no other, so an HTTP worker parses with lxml's stock default and
# expands internal entities where the main thread does not. It is kept because
# it costs nothing and covers the thread module loading happens on, but it is
# not what protects a request: `fromstring`/`parse` below pass the parser
# explicitly and so do not care which thread they run on. Prefer them.
# `test_default_parser_threading.py` pins both halves of this.
etree.set_default_parser(strict_parser)

default_parser = etree.XMLParser(resolve_entities=False, remove_blank_text=True)
default_parser.set_element_class_lookup(objectify.ObjectifyElementClassLookup())
# `objectify.set_default_parser`, unlike etree's, IS global and does reach every
# thread.
objectify.set_default_parser(default_parser)


def fromstring(text: str | bytes, base_url: str | None = None) -> etree._Element:
    """`etree.fromstring` that is hardened whatever thread it runs on."""
    return etree.fromstring(text, parser=strict_parser, base_url=base_url)


def parse(source: str | IO[bytes] | Any, base_url: str | None = None) -> Any:
    """`etree.parse` that is hardened whatever thread it runs on."""
    return etree.parse(source, parser=strict_parser, base_url=base_url)
