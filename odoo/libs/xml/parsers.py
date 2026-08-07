from lxml import etree, objectify

__all__ = ["default_parser"]

etree.set_default_parser(etree.XMLParser(resolve_entities=False, decompress=False))

default_parser = etree.XMLParser(
    resolve_entities=False, remove_blank_text=True, decompress=False
)
default_parser.set_element_class_lookup(objectify.ObjectifyElementClassLookup())
objectify.set_default_parser(default_parser)
